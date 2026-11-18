from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ink_verify.story_graph import (
    BinOp, BoolLit, IntLit, NodeKind, StoryEdge, StoryGraph, StoryNode,
    StringLit, SymExpr, UnaryOp, VarDecl, VarRef, VarType, VisitCount,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eval-stack symbolic interpreter
# ---------------------------------------------------------------------------

BINARY_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "MIN", "MAX"}
UNARY_OPS = {"!", "_"}
CONTROL_STRINGS = {"ev", "/ev", "str", "/str", "out", "du", "pop", "nop",
                   "end", "done", "void", "->->", "~ret", "thread",
                   "choiceCnt", "turn", "turns", "visit", "seq"}


class EvalInterpreter:
    """Symbolically interprets an eval sequence (items between 'ev' and '/ev')."""

    def __init__(self) -> None:
        self.stack: list[SymExpr] = []
        self._in_string_mode = False

    def feed(self, item: object) -> None:
        if isinstance(item, bool):
            self.stack.append(BoolLit(item))
        elif isinstance(item, int):
            self.stack.append(IntLit(item))
        elif isinstance(item, float):
            self.stack.append(IntLit(int(item)))
        elif isinstance(item, dict):
            if "VAR?" in item:
                self.stack.append(VarRef(item["VAR?"]))
            elif "CNT?" in item:
                self.stack.append(VisitCount(item["CNT?"]))
            elif "^->" in item:
                pass
            else:
                self._try_native_function_dict(item)
        elif isinstance(item, str):
            if item == "str":
                self._in_string_mode = True
            elif item == "/str":
                self._in_string_mode = False
            elif item == "du" and self.stack:
                self.stack.append(self.stack[-1])
            elif item == "pop" and self.stack:
                self.stack.pop()
            elif item == "out":
                pass
            elif item == "nop":
                pass
            elif item == "visit":
                pass
            elif self._in_string_mode:
                pass  # ignore string content in string eval mode
            elif item in BINARY_OPS and len(self.stack) >= 2:
                right = self.stack.pop()
                left = self.stack.pop()
                self.stack.append(BinOp(item, left, right))
            elif item in UNARY_OPS and self.stack:
                operand = self.stack.pop()
                self.stack.append(UnaryOp(item, operand))
            # else: ignore other strings (text content, control commands)

    def _try_native_function_dict(self, item: dict) -> None:
        """Handle dict-form native functions like {"+": 2}."""
        for op, arity in item.items():
            if op in BINARY_OPS and isinstance(arity, int) and arity == 2:
                if len(self.stack) >= 2:
                    right = self.stack.pop()
                    left = self.stack.pop()
                    self.stack.append(BinOp(op, left, right))
                return
            if op in UNARY_OPS and isinstance(arity, int) and arity == 1:
                if self.stack:
                    operand = self.stack.pop()
                    self.stack.append(UnaryOp(op, operand))
                return

    def result(self) -> SymExpr | None:
        return self.stack[-1] if self.stack else None

    def clear(self) -> None:
        self.stack.clear()


# ---------------------------------------------------------------------------
# Parse context — accumulates nodes and edges during the walk
# ---------------------------------------------------------------------------

@dataclass
class _ParseContext:
    nodes: dict[str, StoryNode] = field(default_factory=dict)
    edges: list[StoryEdge] = field(default_factory=list)
    variables: dict[str, VarDecl] = field(default_factory=dict)
    entry_node: str = ""
    tunnel_returns: dict[str, str] = field(default_factory=dict)  # tunnel_knot → continuation_node

    def add_node(self, node_id: str, kind: NodeKind, text: str = "") -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = StoryNode(node_id, kind, text)

    def add_edge(self, source: str, target: str, **kwargs) -> None:
        self.edges.append(StoryEdge(source, target, **kwargs))


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_story(json_data: dict) -> StoryGraph:
    """Parse compiled Ink JSON into a StoryGraph."""
    ctx = _ParseContext()

    root = json_data.get("root")
    if not isinstance(root, list) or len(root) < 2:
        raise ValueError("Invalid Ink JSON: 'root' must be a non-empty array")

    # The root container's last element (if dict) holds named knots
    knots_dict = _get_metadata(root)

    # Parse initial content (the first element of root, which is itself a container)
    initial_container = root[0] if isinstance(root[0], list) else None
    _parse_initial(initial_container, root, ctx)

    # Parse global variable declarations
    if knots_dict and "global decl" in knots_dict:
        _parse_global_decl(knots_dict["global decl"], ctx)

    # Parse each knot
    if knots_dict:
        for knot_name, knot_container in knots_dict.items():
            if knot_name.startswith("#") or knot_name == "global decl":
                continue
            if isinstance(knot_container, list):
                _parse_knot(knot_name, knot_container, ctx)

    # Add END terminal if any edge targets it
    _ensure_terminals(ctx)

    if not ctx.entry_node:
        ctx.entry_node = next(iter(ctx.nodes), "")

    graph = StoryGraph(ctx.nodes, ctx.edges, ctx.variables, ctx.entry_node)
    for w in graph.validate():
        log.warning(w)
    return graph


def _get_metadata(container: list) -> dict | None:
    """Get the metadata/named-children dict from a container (its last element if dict)."""
    if not container:
        return None
    last = container[-1]
    if isinstance(last, dict):
        return last
    # Sometimes the second-to-last is a dict when last is null
    if last is None and len(container) >= 2:
        second_last = container[-2]
        if isinstance(second_last, dict):
            return second_last
    return None


def _parse_initial(initial_container: list | None, root: list, ctx: _ParseContext) -> None:
    """Parse the root's initial content to find the entry divert and global variables."""
    if initial_container is None:
        return

    for item in initial_container:
        if isinstance(item, dict):
            if "->" in item and not item.get("var"):
                target = item["->"]
                ctx.entry_node = target
                return
            if "VAR=" in item and "re" not in item:
                _register_variable(item, ctx)

    # Also check root-level items for variable declarations
    for item in root:
        if isinstance(item, dict) and "VAR=" in item and "re" not in item:
            _register_variable(item, ctx)


def _register_variable(item: dict, ctx: _ParseContext) -> None:
    name = item["VAR="]
    val = item.get("val")
    if isinstance(val, bool):
        ctx.variables[name] = VarDecl(name, VarType.BOOL, val)
    elif isinstance(val, int):
        ctx.variables[name] = VarDecl(name, VarType.INT, val)
    elif isinstance(val, float):
        ctx.variables[name] = VarDecl(name, VarType.INT, int(val))
    elif isinstance(val, str):
        ctx.variables[name] = VarDecl(name, VarType.STRING, val)


def _parse_global_decl(container: list, ctx: _ParseContext) -> None:
    """Parse the 'global decl' container for variable declarations.

    Ink compiles all variable declarations into a single eval sequence:
    ev, <value>, {VAR=: name}, <value>, {VAR=: name}, ..., /ev
    """
    eval_interp = EvalInterpreter()
    in_eval = False
    for item in container:
        if item == "ev":
            in_eval = True
            continue
        elif item == "/ev":
            in_eval = False
            continue
        elif in_eval:
            if isinstance(item, dict) and "VAR=" in item and "re" not in item:
                val_expr = eval_interp.result()
                name = item["VAR="]
                if isinstance(val_expr, IntLit):
                    ctx.variables[name] = VarDecl(name, VarType.INT, val_expr.value)
                elif isinstance(val_expr, BoolLit):
                    ctx.variables[name] = VarDecl(name, VarType.BOOL, val_expr.value)
                elif isinstance(val_expr, StringLit):
                    ctx.variables[name] = VarDecl(name, VarType.STRING, val_expr.value)
                else:
                    ctx.variables[name] = VarDecl(name, VarType.INT, 0)
                eval_interp.clear()
            else:
                eval_interp.feed(item)


def _parse_knot(knot_name: str, container: list, ctx: _ParseContext) -> None:
    """Parse a knot container into nodes and edges."""
    ctx.add_node(knot_name, NodeKind.KNOT)

    # Register named sub-containers: stitches and gather points
    _register_named_containers(knot_name, container, ctx)

    # Walk the knot's sequential content
    _walk_container_content(knot_name, container, ctx)


def _register_named_containers(parent_id: str, container: list, ctx: _ParseContext) -> None:
    """Recursively find and register named sub-containers (stitches, gathers)."""
    for item in container:
        if isinstance(item, dict):
            for key, val in item.items():
                if key.startswith("#"):
                    continue
                if isinstance(val, list):
                    sub_id = f"{parent_id}.{key}"
                    if key.startswith("c-"):
                        pass  # choice containers handled by _handle_choice_point
                    elif key.startswith("g-"):
                        ctx.add_node(sub_id, NodeKind.GATHER)
                        _walk_gather_content(sub_id, val, parent_id, ctx)
                    else:
                        ctx.add_node(sub_id, NodeKind.STITCH)
                        _walk_container_content(sub_id, val, ctx)
                        _register_named_containers(sub_id, val, ctx)
        elif isinstance(item, list):
            _register_named_containers(parent_id, item, ctx)


def _walk_gather_content(gather_id: str, container: list, parent_knot: str, ctx: _ParseContext) -> None:
    """Walk a gather container, handling tunnel returns."""
    for item in container:
        if item == "->->":
            # Tunnel return — link to the continuation node if one exists
            if parent_knot in ctx.tunnel_returns:
                ctx.add_edge(gather_id, ctx.tunnel_returns[parent_knot])
            return
        if isinstance(item, str) and item == "done":
            _ensure_terminal_node(ctx, "__DONE__")
            ctx.add_edge(gather_id, "__DONE__")
            return
        if isinstance(item, dict) and "->" in item:
            target = item["->"]
            target = _resolve_relative_path(target, gather_id)
            ctx.add_edge(gather_id, target)
            return


def _parse_stitch(knot_name: str, stitch_name: str, container: list, ctx: _ParseContext) -> None:
    """Parse a stitch within a knot."""
    stitch_id = f"{knot_name}.{stitch_name}"
    ctx.add_node(stitch_id, NodeKind.STITCH)
    _walk_container_content(stitch_id, container, ctx)


def _walk_container_content(node_id: str, container: list, ctx: _ParseContext) -> None:
    """Walk a container's content items to extract edges, choices, and terminals."""
    text_parts: list[str] = []
    metadata = _get_metadata(container)
    in_eval = False
    eval_interp = EvalInterpreter()
    found_divert = False

    # Flatten: if first element is a list, it's an inner container wrapping choices
    items = _flatten_content(container)

    for item in items:
        if isinstance(item, str):
            if item == "ev":
                in_eval = True
                eval_interp.clear()
                continue
            elif item == "/ev":
                in_eval = False
                continue
            elif item == "str" or item == "/str":
                continue
            elif item == "end":
                _ensure_terminal_node(ctx, "__END__")
                ctx.add_edge(node_id, "__END__")
                found_divert = True
                continue
            elif item == "done":
                _ensure_terminal_node(ctx, "__DONE__")
                ctx.add_edge(node_id, "__DONE__")
                found_divert = True
                continue
            elif in_eval:
                eval_interp.feed(item)
                continue
            elif item.startswith("^"):
                text_parts.append(item[1:])
                continue
            elif item == "\n":
                continue

        elif isinstance(item, dict):
            if in_eval:
                eval_interp.feed(item)
                continue

            # Tunnel divert
            if "->t->" in item:
                tunnel_target = item["->t->"]
                ctx.add_edge(node_id, tunnel_target)
                # Create continuation node for content after tunnel
                cont_id = f"{node_id}__cont_{len(ctx.nodes)}"
                ctx.add_node(cont_id, NodeKind.GATHER)
                ctx.tunnel_returns[tunnel_target] = cont_id
                # Walk remaining items as the continuation node
                remaining_idx = items.index(item) + 1
                remaining = items[remaining_idx:]
                if remaining:
                    _walk_container_content(cont_id, remaining + [None], ctx)
                return

            # Tunnel return
            if "->" in item and item["->"] == "->->":
                continue
            if item == "->->":
                continue

            # Divert
            if "->" in item and "*" not in item:
                target = item["->"]
                if item.get("var"):
                    continue  # variable divert — skip for now
                # Resolve relative paths
                target = _resolve_relative_path(target, node_id)
                guard = None
                if item.get("c"):
                    guard = eval_interp.result()
                    eval_interp.clear()
                ctx.add_edge(node_id, target, guard=guard)
                found_divert = True
                continue

            # ChoicePoint
            if "*" in item:
                _handle_choice_point(node_id, item, container, eval_interp, ctx)
                eval_interp.clear()
                continue

            # Variable declaration (new)
            if "VAR=" in item and "re" not in item:
                _register_variable(item, ctx)
                continue

            # Variable reassignment (uses last eval result)
            if "VAR=" in item and item.get("re"):
                val = eval_interp.result()
                if val is not None:
                    # Store mutation on the current node — will be attached to edges later
                    pass  # mutations in walk context are on choice content, handled in _extract_choice_content
                eval_interp.clear()
                continue

        elif isinstance(item, list):
            # Nested container — walk recursively for inner choices
            inner_meta = _get_metadata(item)
            _walk_container_content(node_id, item, ctx)

        elif isinstance(item, (int, float)):
            if in_eval:
                eval_interp.feed(item)

    if text_parts:
        node = ctx.nodes.get(node_id)
        if node:
            node.text = "".join(text_parts).strip()


def _flatten_content(container: list) -> list:
    """Extract sequential content items from a container, excluding the metadata dict and None."""
    items = []
    for item in container:
        if item is None:
            continue
        if isinstance(item, dict):
            # Check if this is the terminal metadata dict
            if any(k.startswith("#") for k in item):
                # Could be metadata but could also have named containers
                # Keep it for processing of named sub-containers
                continue
            items.append(item)
        else:
            items.append(item)
    return items


def _handle_choice_point(
    node_id: str,
    choice_item: dict,
    parent_container: list,
    eval_interp: EvalInterpreter,
    ctx: _ParseContext,
) -> None:
    """Process a ChoicePoint and create an edge to its target."""
    choice_path = choice_item["*"]
    flags = choice_item.get("flg", 0)

    has_condition = bool(flags & 0x1)
    has_start_content = bool(flags & 0x2)
    has_choice_only_content = bool(flags & 0x4)
    is_invisible_default = bool(flags & 0x8)
    is_once_only = bool(flags & 0x10)

    guard = None
    if has_condition:
        guard = eval_interp.result()

    # Resolve the choice target — find the named sub-container
    choice_container_name = _resolve_choice_path(choice_path)
    choice_container = _find_named_container(parent_container, choice_container_name)

    # Extract the divert target, text, and mutations from the choice content
    target = ""
    choice_text = ""
    mutations = []
    if choice_container:
        target, choice_text, mutations = _extract_choice_content(choice_container)

    if target:
        target = _resolve_relative_path(target, node_id)
        ctx.add_edge(
            node_id, target,
            guard=guard,
            mutations=mutations,
            once_only=is_once_only,
            is_fallback=is_invisible_default,
            choice_text=choice_text,
        )


def _resolve_choice_path(path: str) -> str:
    """Extract the choice container name from a relative path like '.^.c-0'."""
    parts = path.split(".")
    # Typical: ".^.c-0" means parent's named container "c-0"
    # We just want the last part (the container name)
    return parts[-1] if parts else path


def _find_named_container(container: list, name: str) -> list | None:
    """Find a named sub-container within a container's metadata dict."""
    # Search in all dict items in the container
    for item in container:
        if isinstance(item, dict) and name in item:
            val = item[name]
            if isinstance(val, list):
                return val
        # Also search in nested lists (inner containers)
        if isinstance(item, list):
            result = _find_named_container(item, name)
            if result is not None:
                return result
    return None


def _extract_choice_content(container: list) -> tuple[str, str, list[tuple[str, SymExpr]]]:
    """Extract divert target, text, and mutations from a choice content container."""
    target = None
    text_parts = []
    mutations = []
    eval_interp = EvalInterpreter()
    in_eval = False

    for item in container:
        if isinstance(item, str):
            if item == "ev":
                in_eval = True
                eval_interp.clear()
                continue
            elif item == "/ev":
                in_eval = False
                continue
            elif in_eval:
                eval_interp.feed(item)
                continue
            elif item.startswith("^"):
                text_parts.append(item[1:])
                continue
        elif isinstance(item, (int, float)):
            if in_eval:
                eval_interp.feed(item)
                continue
        elif isinstance(item, dict):
            if in_eval:
                eval_interp.feed(item)
                continue
            if "->" in item and "*" not in item:
                target = item["->"]
            elif "VAR=" in item and item.get("re"):
                val = eval_interp.result()
                if val is not None:
                    mutations.append((item["VAR="], val))
                eval_interp.clear()
            elif "f()" in item:
                pass

    return target or "", "".join(text_parts).strip(), mutations


def _resolve_relative_path(path: str, context_node: str) -> str:
    """Resolve a relative path like '.^.^.g-0' to an absolute node id."""
    if not path.startswith("."):
        return path
    # Extract the base knot from context (e.g., "crossing" from "crossing")
    base_knot = context_node.split(".")[0] if "." in context_node else context_node
    # Parse the relative path
    parts = path.split(".")
    # The last part is the target name
    target_name = parts[-1] if parts else path
    # Return as knot.target_name
    return f"{base_knot}.{target_name}"


def _ensure_terminal_node(ctx: _ParseContext, node_id: str) -> None:
    if node_id not in ctx.nodes:
        ctx.add_node(node_id, NodeKind.TERMINAL)


def _ensure_terminals(ctx: _ParseContext) -> None:
    """Add terminal nodes for any edge targets that don't exist yet."""
    all_targets = {e.target for e in ctx.edges}
    for t in all_targets:
        if t not in ctx.nodes:
            if t in ("END", "DONE", "__END__", "__DONE__"):
                ctx.add_node(t, NodeKind.TERMINAL)
