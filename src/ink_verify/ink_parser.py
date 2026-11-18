from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ink_verify.story_graph import (
    BinOp, BoolLit, IntLit, NodeKind, StoryEdge, StoryGraph, StoryNode,
    StringLit, SymExpr, UnaryOp, VarDecl, VarRef, VarType, VisitCount,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eval-stack symbolic interpreter (unchanged)
# ---------------------------------------------------------------------------

BINARY_OPS = {"+", "-", "*", "/", "%", "==", "!=", "<", ">", "<=", ">=", "&&", "||", "MIN", "MAX"}
UNARY_OPS = {"!", "_"}


class EvalInterpreter:
    def __init__(self) -> None:
        self.stack: list[SymExpr] = []
        self._in_string_mode = False
        self._string_parts: list[str] = []

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
                self._string_parts = []
            elif item == "/str":
                self._in_string_mode = False
                text = "".join(self._string_parts)
                self.stack.append(StringLit(text))
            elif item == "du" and self.stack:
                self.stack.append(self.stack[-1])
            elif item == "pop" and self.stack:
                self.stack.pop()
            elif item in ("out", "nop", "visit"):
                pass
            elif self._in_string_mode:
                if item.startswith("^"):
                    self._string_parts.append(item[1:])
            elif item in BINARY_OPS and len(self.stack) >= 2:
                right = self.stack.pop()
                left = self.stack.pop()
                self.stack.append(BinOp(item, left, right))
            elif item in UNARY_OPS and self.stack:
                operand = self.stack.pop()
                self.stack.append(UnaryOp(item, operand))

    def _try_native_function_dict(self, item: dict) -> None:
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
# Container tree — maps every path in the JSON to its content
# ---------------------------------------------------------------------------

@dataclass
class CNode:
    path: str
    content: list
    parent: CNode | None = None
    named: dict[str, CNode] = field(default_factory=dict)
    positional: dict[int, CNode] = field(default_factory=dict)
    flags: int = 0
    name: str = ""


def _build_tree(container: list, path: str, parent: CNode | None) -> CNode:
    node = CNode(path=path, content=container, parent=parent)

    # Find metadata dict (last element if dict, or second-to-last if last is null)
    meta = None
    if container:
        last = container[-1]
        if isinstance(last, dict):
            meta = last
        elif last is None and len(container) >= 2 and isinstance(container[-2], dict):
            meta = container[-2]

    if meta:
        node.flags = meta.get("#f", 0)
        node.name = meta.get("#n", "")
        for key, val in meta.items():
            if key.startswith("#"):
                continue
            if isinstance(val, list):
                child_path = f"{path}.{key}" if path else key
                child = _build_tree(val, child_path, node)
                node.named[key] = child

    # Register positional children (arrays in the content, before the metadata)
    content_end = len(container)
    if meta is not None:
        content_end = container.index(meta) if meta in container else content_end
    for i, item in enumerate(container[:content_end]):
        if isinstance(item, list):
            child_path = f"{path}.{i}" if path else str(i)
            child = _build_tree(item, child_path, node)
            node.positional[i] = child

    return node


def _resolve_inside(path_str: str, container: CNode) -> CNode | None:
    """Resolve a path found INSIDE a container (e.g., a divert within c-0).

    The path starts from a position within the container, so the first ^
    returns to the container itself, not its parent.
    """
    dummy = CNode(path=f"{container.path}.__pos", content=[], parent=container)
    return _resolve(path_str, dummy)


def _resolve(path_str: str, context: CNode) -> CNode | None:
    """Resolve a relative or absolute path against the container tree."""
    if not path_str.startswith("."):
        # Absolute path — walk from root
        root = context
        while root.parent is not None:
            root = root.parent
        return _walk_path(path_str.split("."), root)

    # Relative path: split on ".", skip leading empty segment
    segments = path_str.split(".")
    cur = context
    for seg in segments:
        if not seg:
            continue
        if seg == "^":
            if cur.parent:
                cur = cur.parent
        elif seg.isdigit():
            idx = int(seg)
            if idx in cur.positional:
                cur = cur.positional[idx]
            else:
                return None
        else:
            if seg in cur.named:
                cur = cur.named[seg]
            else:
                return None
    return cur


def _resolve_partial(path_str: str, context: CNode, tree: CNode) -> CNode | None:
    """Resolve a path as far as possible, returning the last valid CNode reached."""
    if path_str.startswith("."):
        # Start from inside the context
        dummy = CNode(path=f"{context.path}.__pos", content=[], parent=context)
        cur = dummy
        segments = path_str.split(".")
    else:
        cur = tree
        segments = path_str.split(".")

    last_valid = cur
    for seg in segments:
        if not seg:
            continue
        if seg == "^":
            if cur.parent:
                cur = cur.parent
                last_valid = cur
            else:
                break
        elif seg.isdigit():
            idx = int(seg)
            if idx in cur.positional:
                cur = cur.positional[idx]
                last_valid = cur
            else:
                break
        else:
            if seg in cur.named:
                cur = cur.named[seg]
                last_valid = cur
            else:
                break

    return last_valid if last_valid.path else None


def _walk_path(segments: list[str], root: CNode) -> CNode | None:
    cur = root
    for seg in segments:
        if not seg:
            continue
        if seg.isdigit():
            idx = int(seg)
            if idx in cur.positional:
                cur = cur.positional[idx]
            else:
                return None
        else:
            if seg in cur.named:
                cur = cur.named[seg]
            else:
                return None
    return cur


# ---------------------------------------------------------------------------
# Story node identification — which containers become graph nodes
# ---------------------------------------------------------------------------

def _node_id_for(cnode: CNode) -> str:
    """Derive a story-graph node id from a container's path.

    Strip positional segments to get a human-readable id:
    "start.0.6.suggest_its_a_lie" → "start.suggest_its_a_lie"
    But keep the full path as fallback for uniqueness.
    """
    parts = cnode.path.split(".")
    named_parts = [p for p in parts if not p.isdigit()]
    short = ".".join(named_parts)
    return short if short else cnode.path


def _find_story_node(cnode: CNode, registered: set[str]) -> str | None:
    """Walk up from cnode to find the nearest registered story node."""
    cur = cnode
    while cur is not None:
        nid = _node_id_for(cur)
        if nid in registered:
            return nid
        cur = cur.parent
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_story(json_data: dict, source_index=None) -> StoryGraph:
    """Parse compiled Ink JSON into a StoryGraph.

    If source_index (a SourceIndex from .ink files) is provided, use it
    to correct variable types — the compiled JSON loses string vs int
    distinction.
    """
    root = json_data.get("root")
    if not isinstance(root, list) or len(root) < 2:
        raise ValueError("Invalid Ink JSON: 'root' must be a non-empty array")

    # Phase 1: Build the container tree
    tree = _build_tree(root, "", None)

    # Phase 2: Extract global variables
    variables: dict[str, VarDecl] = {}
    if "global decl" in tree.named:
        _parse_global_decl(tree.named["global decl"].content, variables)

    # Phase 2b: Correct variable types from source if available
    if source_index:
        for vname, vdecl in list(variables.items()):
            src_type = source_index.var_type(vname)
            if src_type and src_type != vdecl.var_type:
                if src_type == VarType.STRING:
                    variables[vname] = VarDecl(vname, VarType.STRING, "")
                elif src_type == VarType.BOOL:
                    variables[vname] = VarDecl(vname, VarType.BOOL, bool(vdecl.initial_value))

    # Phase 3: Register story nodes (knots, stitches, gathers)
    nodes: dict[str, StoryNode] = {}
    cnode_to_id: dict[int, str] = {}

    for key, child in tree.named.items():
        if key == "global decl" or key.startswith("#"):
            continue
        nid = _node_id_for(child)
        if nid not in nodes:
            nodes[nid] = StoryNode(nid, NodeKind.KNOT)
        cnode_to_id[id(child)] = nid
        _register_descendants(child, nodes, cnode_to_id)

    # Phase 4: Find entry point — scan initial content for all diverts to knots
    knot_names = set(nodes.keys())
    entry_node = _find_entry(tree, knot_names)

    # Phase 5: Walk containers to extract edges
    edges: list[StoryEdge] = []
    tunnel_returns: dict[str, str] = {}
    registered_ids = set(nodes.keys())

    # Walk initial content for edges (root[0] container)
    init_cnode = tree.positional.get(0)
    if init_cnode:
        _extract_edges(init_cnode, entry_node or "__ROOT__", tree, nodes,
                        cnode_to_id, edges, variables, tunnel_returns, registered_ids)

    for key, knot_cnode in tree.named.items():
        if key == "global decl" or key.startswith("#"):
            continue
        knot_id = _node_id_for(knot_cnode)
        _extract_edges(knot_cnode, knot_id, tree, nodes, cnode_to_id, edges,
                        variables, tunnel_returns, registered_ids)

    # Phase 6: Add terminals
    _add_terminal(nodes, "__END__")
    _add_terminal(nodes, "__DONE__")

    # Clean up edges with unresolvable targets
    valid_edges = []
    dropped = 0
    for e in edges:
        if e.target not in nodes:
            dropped += 1
        else:
            valid_edges.append(e)

    if dropped:
        log.info("Dropped %d edges with unresolvable targets (%d edges kept)",
                  dropped, len(valid_edges))

    if not entry_node:
        entry_node = next(iter(nodes), "")

    graph = StoryGraph(nodes, valid_edges, variables, entry_node)
    graph._dropped_edges = dropped  # type: ignore[attr-defined]
    return graph


def _find_entry(tree: CNode, knot_names: set[str]) -> str:
    """Find the story entry point by scanning initial content for the first
    divert that targets a registered knot."""
    def _scan(obj: object) -> str:
        if isinstance(obj, list):
            for item in obj:
                result = _scan(item)
                if result:
                    return result
        elif isinstance(obj, dict):
            if "->" in obj and not obj.get("var") and not obj.get("c"):
                target = obj["->"]
                if target in knot_names:
                    return target
            for val in obj.values():
                result = _scan(val)
                if result:
                    return result
        return ""

    init = tree.positional.get(0)
    if init:
        return _scan(init.content)
    return ""


def _register_descendants(cnode: CNode, nodes: dict, cnode_to_id: dict) -> None:
    """Register stitches, gathers, and other named sub-containers as story nodes."""
    for name, child in cnode.named.items():
        if name.startswith("#"):
            continue
        nid = _node_id_for(child)
        if name.startswith("c-"):
            # Choice containers — don't register as nodes, but recurse for inner gathers
            _register_descendants(child, nodes, cnode_to_id)
        elif name.startswith("g-"):
            if nid not in nodes:
                nodes[nid] = StoryNode(nid, NodeKind.GATHER)
            cnode_to_id[id(child)] = nid
            _register_descendants(child, nodes, cnode_to_id)
        else:
            if nid not in nodes:
                nodes[nid] = StoryNode(nid, NodeKind.STITCH)
            cnode_to_id[id(child)] = nid
            _register_descendants(child, nodes, cnode_to_id)

    for idx, child in cnode.positional.items():
        _register_descendants(child, nodes, cnode_to_id)


def _resolve_target(path_str: str, context: CNode, tree: CNode,
                     nodes: dict, cnode_to_id: dict,
                     inside: bool = True) -> str:
    """Resolve a divert target path to a story node id.

    When inside=True (default), the path is resolved as if found INSIDE
    the context container (first ^ returns to context itself).
    """
    if path_str in ("->->",):
        return ""

    if path_str.startswith("."):
        resolved = _resolve_inside(path_str, context) if inside else _resolve(path_str, context)
    else:
        resolved = _resolve(path_str, tree)

    if resolved is None:
        # Fallback: walk the path as far as possible, then map to nearest ancestor node
        resolved = _resolve_partial(path_str, context if inside else context, tree)
        if resolved is None:
            return path_str

    # Find the node id for this container
    rid = id(resolved)
    if rid in cnode_to_id:
        return cnode_to_id[rid]

    # Walk up to find the nearest registered node
    cur = resolved
    while cur is not None:
        cid = id(cur)
        if cid in cnode_to_id:
            return cnode_to_id[cid]
        cur = cur.parent

    return _node_id_for(resolved)


def _extract_edges(cnode: CNode, current_node: str, tree: CNode,
                    nodes: dict, cnode_to_id: dict,
                    edges: list, variables: dict,
                    tunnel_returns: dict, registered: set) -> None:
    """Walk a container's content to extract edges."""
    content = cnode.content
    eval_interp = EvalInterpreter()
    in_eval = False

    # Find content boundary (before metadata dict)
    meta_idx = len(content)
    for i, item in enumerate(content):
        if isinstance(item, dict) and any(k.startswith("#") for k in item):
            meta_idx = i
            break
        if item is None:
            meta_idx = i
            break

    i = 0
    while i < meta_idx:
        item = content[i]
        i += 1

        # --- Strings ---
        if isinstance(item, str):
            if item == "ev":
                in_eval = True
                eval_interp.clear()
                continue
            if item == "/ev":
                in_eval = False
                continue
            if in_eval:
                eval_interp.feed(item)
                continue
            if item == "end":
                edges.append(StoryEdge(current_node, "__END__"))
                continue
            if item == "done":
                edges.append(StoryEdge(current_node, "__DONE__"))
                continue
            if item == "->->":
                # Tunnel return
                knot_name = current_node.split(".")[0]
                if knot_name in tunnel_returns:
                    edges.append(StoryEdge(current_node, tunnel_returns[knot_name]))
                continue
            continue

        # --- Numbers in eval ---
        if isinstance(item, (int, float)):
            if in_eval:
                eval_interp.feed(item)
            continue

        # --- Dicts ---
        if isinstance(item, dict):
            if in_eval:
                eval_interp.feed(item)
                continue

            # Tunnel divert
            if "->t->" in item:
                tunnel_target = item["->t->"]
                target_id = _resolve_target(tunnel_target, cnode, tree, nodes, cnode_to_id)
                edges.append(StoryEdge(current_node, target_id))
                cont_id = f"{current_node}__cont_{len(nodes)}"
                nodes[cont_id] = StoryNode(cont_id, NodeKind.GATHER)
                registered.add(cont_id)
                tunnel_returns[target_id] = cont_id
                # Remaining content belongs to continuation
                remaining = content[i:meta_idx]
                if remaining:
                    fake_cnode = CNode(path=cont_id, content=remaining + [None], parent=cnode)
                    _extract_edges(fake_cnode, cont_id, tree, nodes, cnode_to_id,
                                    edges, variables, tunnel_returns, registered)
                return

            # Divert
            if "->" in item and "*" not in item:
                target_path = item["->"]
                if item.get("var"):
                    continue
                target_id = _resolve_target(target_path, cnode, tree, nodes, cnode_to_id)
                guard = None
                if item.get("c"):
                    guard = eval_interp.result()
                    eval_interp.clear()
                if target_id:
                    edges.append(StoryEdge(current_node, target_id, guard=guard))
                continue

            # ChoicePoint
            if "*" in item:
                _handle_choice(item, cnode, current_node, eval_interp, tree,
                               nodes, cnode_to_id, edges)
                eval_interp.clear()
                continue

            # Variable reassignment
            if "VAR=" in item and item.get("re"):
                eval_interp.clear()
                continue

            continue

        # --- Nested containers (arrays) ---
        if isinstance(item, list):
            # Find this item's CNode in positional children
            idx = i - 1
            child_cnode = cnode.positional.get(idx)
            if child_cnode:
                _extract_edges(child_cnode, current_node, tree, nodes, cnode_to_id,
                               edges, variables, tunnel_returns, registered)
            else:
                fake = CNode(path=f"{cnode.path}.{idx}", content=item, parent=cnode)
                _extract_edges(fake, current_node, tree, nodes, cnode_to_id,
                               edges, variables, tunnel_returns, registered)

    # Also process named sub-containers that are stitches (not choices, gathers handled separately)
    for name, child in cnode.named.items():
        if name.startswith("#") or name.startswith("c-"):
            continue
        child_id = _node_id_for(child)
        if child_id in nodes and child_id != current_node:
            _extract_edges(child, child_id, tree, nodes, cnode_to_id,
                           edges, variables, tunnel_returns, registered)

    # Process gather containers
    for name, child in cnode.named.items():
        if name.startswith("g-"):
            gather_id = _node_id_for(child)
            if gather_id in nodes:
                _extract_gather(child, gather_id, tree, nodes, cnode_to_id,
                                edges, tunnel_returns)


def _extract_gather(cnode: CNode, gather_id: str, tree: CNode,
                     nodes: dict, cnode_to_id: dict,
                     edges: list, tunnel_returns: dict) -> None:
    """Extract edges from a gather container."""
    for item in cnode.content:
        if item is None:
            continue
        if isinstance(item, str):
            if item == "->->":
                knot_name = gather_id.split(".")[0]
                if knot_name in tunnel_returns:
                    edges.append(StoryEdge(gather_id, tunnel_returns[knot_name]))
                return
            if item == "done":
                edges.append(StoryEdge(gather_id, "__DONE__"))
                return
            if item == "end":
                edges.append(StoryEdge(gather_id, "__END__"))
                return
        if isinstance(item, dict):
            if "->" in item and not item.get("var"):
                target = _resolve_target(item["->"], cnode, tree, nodes, cnode_to_id)
                if target:
                    edges.append(StoryEdge(gather_id, target))
                return


def _handle_choice(choice_item: dict, context_cnode: CNode, current_node: str,
                    eval_interp: EvalInterpreter, tree: CNode,
                    nodes: dict, cnode_to_id: dict, edges: list) -> None:
    """Process a ChoicePoint into a story edge."""
    choice_path = choice_item["*"]
    flags = choice_item.get("flg", 0)
    has_condition = bool(flags & 0x1)
    is_invisible_default = bool(flags & 0x8)
    is_once_only = bool(flags & 0x10)

    guard = eval_interp.result() if has_condition else None

    # Find the choice content container via the tree
    choice_cnode = _resolve_inside(choice_path, context_cnode)

    target = ""
    choice_text = ""
    mutations: list[tuple[str, SymExpr]] = []

    if choice_cnode:
        target_path, choice_text, mutations = _extract_choice_content(choice_cnode.content)
        if target_path:
            target = _resolve_target(target_path, choice_cnode, tree, nodes, cnode_to_id)
    else:
        # Fallback: try to find the choice container by name
        name = choice_path.split(".")[-1]
        container = _find_named_in_tree(context_cnode, name)
        if container:
            target_path, choice_text, mutations = _extract_choice_content(container)
            if target_path:
                target = _resolve_target(target_path, context_cnode, tree, nodes, cnode_to_id)

    if target:
        edges.append(StoryEdge(
            current_node, target,
            guard=guard, mutations=mutations,
            once_only=is_once_only, is_fallback=is_invisible_default,
            choice_text=choice_text,
        ))


def _find_named_in_tree(cnode: CNode, name: str) -> list | None:
    """Search for a named container in cnode and its positional children."""
    if name in cnode.named:
        return cnode.named[name].content
    for child in cnode.positional.values():
        result = _find_named_in_tree(child, name)
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

    return target or "", "".join(text_parts).strip(), mutations


# ---------------------------------------------------------------------------
# Global variable declarations (unchanged)
# ---------------------------------------------------------------------------

def _parse_global_decl(container: list, variables: dict[str, VarDecl]) -> None:
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
                    variables[name] = VarDecl(name, VarType.INT, val_expr.value)
                elif isinstance(val_expr, BoolLit):
                    variables[name] = VarDecl(name, VarType.BOOL, val_expr.value)
                elif isinstance(val_expr, StringLit):
                    variables[name] = VarDecl(name, VarType.STRING, val_expr.value)
                else:
                    variables[name] = VarDecl(name, VarType.INT, 0)
                eval_interp.clear()
            else:
                eval_interp.feed(item)


def _add_terminal(nodes: dict, nid: str) -> None:
    if nid not in nodes:
        nodes[nid] = StoryNode(nid, NodeKind.TERMINAL)
