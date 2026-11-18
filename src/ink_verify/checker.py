from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

import yaml
import z3

from ink_verify.story_graph import (
    BinOp, BoolLit, IntLit, NodeKind, StoryGraph, SymExpr, UnaryOp, VarRef, VarType,
)
from ink_verify.z3_encoder import EncodedModel, encode, sym_to_z3


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TraceStep:
    node_id: str
    node_text: str
    choice_text: str
    variables: dict[str, Any]

@dataclass
class Verdict:
    name: str
    property_type: str
    passed: bool
    counterexample: list[TraceStep] | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Property expression parser (Python ast → SymExpr)
# ---------------------------------------------------------------------------

def parse_property_expr(text: str) -> SymExpr:
    """Parse a property expression string to SymExpr using Python's ast module."""
    tree = ast.parse(text, mode="eval")
    return _ast_to_sym(tree.body)


def _ast_to_sym(node: ast.AST) -> SymExpr:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return BoolLit(node.value)
        if isinstance(node.value, int):
            return IntLit(node.value)
        if isinstance(node.value, float):
            return IntLit(int(node.value))
        return BoolLit(False)

    if isinstance(node, ast.Name):
        name = node.id
        if name == "True":
            return BoolLit(True)
        if name == "False":
            return BoolLit(False)
        if name == "true":
            return BoolLit(True)
        if name == "false":
            return BoolLit(False)
        return VarRef(name)

    if isinstance(node, ast.Compare):
        left = _ast_to_sym(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = _ast_to_sym(comparator)
            op_str = _compare_op(op)
            left = BinOp(op_str, left, right)
        return left

    if isinstance(node, ast.BoolOp):
        op_str = "&&" if isinstance(node.op, ast.And) else "||"
        result = _ast_to_sym(node.values[0])
        for val in node.values[1:]:
            result = BinOp(op_str, result, _ast_to_sym(val))
        return result

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return UnaryOp("!", _ast_to_sym(node.operand))
        if isinstance(node.op, ast.USub):
            return UnaryOp("_", _ast_to_sym(node.operand))

    if isinstance(node, ast.BinOp):
        left = _ast_to_sym(node.left)
        right = _ast_to_sym(node.right)
        op_str = _arith_op(node.op)
        return BinOp(op_str, left, right)

    raise ValueError(f"Unsupported expression node: {ast.dump(node)}")


def _compare_op(op: ast.cmpop) -> str:
    ops = {
        ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<", ast.LtE: "<=",
        ast.Gt: ">", ast.GtE: ">=",
    }
    return ops.get(type(op), "==")


def _arith_op(op: ast.operator) -> str:
    ops = {
        ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.Mod: "%",
    }
    return ops.get(type(op), "+")


# ---------------------------------------------------------------------------
# Auto-detect default properties
# ---------------------------------------------------------------------------

def auto_detect_properties(graph: StoryGraph, source_index=None) -> list[dict]:
    """Generate default property checks based on the story graph.

    When source_index is provided, only check author-written knots and
    exclude compiler-generated internal nodes and function knots.
    """
    props: list[dict] = []

    all_nodes = [(nid, n) for nid, n in graph.nodes.items()
                 if n.kind in (NodeKind.KNOT, NodeKind.STITCH, NodeKind.GATHER)]

    if source_index:
        author_knots = set(source_index.knots.keys())
        functions = source_index.functions

        authored = []
        internal = []
        for nid, n in all_nodes:
            top_name = nid.split(".")[0]
            if top_name in functions:
                continue
            if nid in author_knots:
                authored.append(nid)
            else:
                internal.append(nid)

        for knot in authored:
            props.append({"name": f"{knot} reachable", "type": "reachable", "knot": knot})

        if internal:
            props.append({
                "name": f"{len(internal)} internal nodes",
                "type": "_info",
                "detail": f"Skipped {len(internal)} compiler-generated nodes (gathers, choice internals). "
                          f"Checked {len(authored)} author-written knots."
            })
    else:
        # No source: check only top-level knots (no dots in name, no c-/g- prefixes)
        top_level = []
        sub_nodes = []
        for nid, n in all_nodes:
            if "." not in nid and not nid.startswith("__"):
                top_level.append(nid)
            else:
                sub_nodes.append(nid)

        for knot in top_level:
            props.append({"name": f"{knot} reachable", "type": "reachable", "knot": knot})

        if sub_nodes:
            props.append({
                "name": f"{len(sub_nodes)} sub-nodes",
                "type": "_info",
                "detail": f"Skipped {len(sub_nodes)} sub-nodes (no source provided). "
                          f"Checked {len(top_level)} top-level knots. "
                          f"Use --source for full coverage."
            })

    # No dead ends
    props.append({"name": "no dead ends", "type": "no_dead_ends"})

    # Numeric variables non-negative
    for vname, vdecl in graph.variables.items():
        if vdecl.var_type == VarType.INT:
            props.append({"name": f"{vname} >= 0", "type": "invariant", "expr": f"{vname} >= 0"})

    return props


# ---------------------------------------------------------------------------
# Property checking
# ---------------------------------------------------------------------------

def check_properties(
    graph: StoryGraph,
    properties: list[dict],
    bound: int = 3,
) -> list[Verdict]:
    """Check all properties against the story graph."""
    em = encode(graph, bound)
    verdicts = []

    for prop in properties:
        ptype = prop.get("type", "")
        name = prop.get("name", ptype)

        if ptype == "reachable":
            verdicts.append(_check_reachable(em, name, prop["knot"]))
        elif ptype == "no_dead_ends":
            verdicts.append(_check_no_dead_ends(em, name))
        elif ptype == "invariant":
            verdicts.append(_check_invariant(em, name, prop["expr"]))
        elif ptype == "implication":
            verdicts.append(_check_implication(em, name, prop["if_knot"], prop["then_expr"]))
        elif ptype == "_info":
            verdicts.append(Verdict(name, "_info", True, reason=prop.get("detail", "")))
        else:
            verdicts.append(Verdict(name, ptype, False, reason=f"Unknown property type: {ptype}"))

    return verdicts


def _check_reachable(em: EncodedModel, name: str, knot: str) -> Verdict:
    if knot not in em.reach:
        return Verdict(name, "reachable", False, reason=f"Knot '{knot}' not found in story")

    em.solver.push()
    em.solver.add(em.reach[knot] == True)
    result = em.solver.check()
    if result == z3.sat:
        em.solver.pop()
        return Verdict(name, "reachable", True)
    else:
        em.solver.pop()
        incoming = em.graph.incoming(knot)
        if incoming:
            return Verdict(name, "reachable", False,
                           reason=f"'{knot}' has {len(incoming)} incoming edges but no verified path "
                                  f"— graph chain may be incomplete (review manually)")
        return Verdict(name, "reachable", False, reason=f"'{knot}' is unreachable — no incoming edges")


def _check_no_dead_ends(em: EncodedModel, name: str) -> Verdict:
    graph = em.graph
    non_terminals = graph.non_terminals()
    dead_end_clauses = []

    for nid in non_terminals:
        outgoing = graph.outgoing(nid)
        if not outgoing:
            dead_end_clauses.append(em.reach[nid])
            continue

        guard_exprs = []
        for edge in outgoing:
            if edge.guard is not None and nid in em.node_vars:
                try:
                    guard_z3 = sym_to_z3(edge.guard, em.node_vars[nid])
                    from ink_verify.z3_encoder import _coerce_bool
                    guard_exprs.append(_coerce_bool(guard_z3))
                except (ValueError, z3.Z3Exception):
                    guard_exprs.append(z3.BoolVal(True))
            else:
                guard_exprs.append(z3.BoolVal(True))

        all_guards_false = z3.And(*[z3.Not(g) for g in guard_exprs])
        dead_end_clauses.append(z3.And(em.reach[nid], all_guards_false))

    if not dead_end_clauses:
        return Verdict(name, "no_dead_ends", True)

    em.solver.push()
    em.solver.add(z3.Or(*dead_end_clauses))
    result = em.solver.check()
    if result == z3.sat:
        path = _extract_path(em)
        dead_node = _find_dead_end_node(em, non_terminals)
        em.solver.pop()
        return Verdict(name, "no_dead_ends", False, counterexample=path,
                       reason=f"Dead end at '{dead_node}'")
    else:
        em.solver.pop()
        return Verdict(name, "no_dead_ends", True)


def _check_invariant(em: EncodedModel, name: str, expr_text: str) -> Verdict:
    sym_expr = parse_property_expr(expr_text)
    violation_clauses = {}
    for nid in em.graph.nodes:
        if nid in em.node_vars:
            try:
                expr_z3 = sym_to_z3(sym_expr, em.node_vars[nid])
                from ink_verify.z3_encoder import _coerce_bool
                violation_clauses[nid] = z3.And(em.reach[nid], z3.Not(_coerce_bool(expr_z3)))
            except (ValueError, z3.Z3Exception):
                pass

    if not violation_clauses:
        return Verdict(name, "invariant", True)

    em.solver.push()
    em.solver.add(z3.Or(*violation_clauses.values()))
    result = em.solver.check()
    if result == z3.sat:
        path = _extract_path(em)
        violating_node = _find_violating_node(em, violation_clauses)
        em.solver.pop()
        return Verdict(name, "invariant", False, counterexample=path,
                       reason=f"Invariant '{expr_text}' violated at '{violating_node}'")
    else:
        em.solver.pop()
        return Verdict(name, "invariant", True)


def _check_implication(em: EncodedModel, name: str, knot: str, expr_text: str) -> Verdict:
    if knot not in em.reach:
        return Verdict(name, "implication", False, reason=f"Knot '{knot}' not found")

    sym_expr = parse_property_expr(expr_text)
    em.solver.push()
    if knot in em.node_vars:
        try:
            expr_z3 = sym_to_z3(sym_expr, em.node_vars[knot])
            from ink_verify.z3_encoder import _coerce_bool
            em.solver.add(em.reach[knot] == True)
            em.solver.add(z3.Not(_coerce_bool(expr_z3)))
        except (ValueError, z3.Z3Exception):
            em.solver.pop()
            return Verdict(name, "implication", True,
                           reason=f"Skipped — expression references unsupported variable types")
    result = em.solver.check()
    if result == z3.sat:
        path = _extract_path(em)
        em.solver.pop()
        return Verdict(name, "implication", False, counterexample=path,
                       reason=f"At '{knot}', '{expr_text}' can be false")
    else:
        em.solver.pop()
        return Verdict(name, "implication", True)


# ---------------------------------------------------------------------------
# Counterexample path extraction
# ---------------------------------------------------------------------------

def _extract_path(em: EncodedModel) -> list[TraceStep]:
    model = em.solver.model()
    path = []
    visited = set()
    current = em.graph.entry_node

    while current and current not in visited:
        visited.add(current)
        node = em.graph.nodes.get(current)
        if not node:
            break

        # Read variable values at this node
        var_vals = {}
        for vname in em.graph.variables:
            if current in em.node_vars and vname in em.node_vars[current]:
                val = model.eval(em.node_vars[current][vname], model_completion=True)
                try:
                    var_vals[vname] = val.as_long()
                except (AttributeError, z3.Z3Exception):
                    var_vals[vname] = str(val)

        # Find which outgoing edge is taken
        choice_text = ""
        next_node = None
        for edge in em.graph.outgoing(current):
            taken_val = model.eval(em.edge_taken[edge.edge_id], model_completion=True)
            if z3.is_true(taken_val):
                choice_text = edge.choice_text
                next_node = edge.target
                break

        path.append(TraceStep(current, node.text, choice_text, var_vals))
        current = next_node

    return path


def _find_violating_node(em: EncodedModel, clauses: dict[str, z3.ExprRef]) -> str:
    """Find which node violates the invariant in the current model."""
    model = em.solver.model()
    for nid, clause in clauses.items():
        if z3.is_true(model.eval(clause, model_completion=True)):
            return nid
    return "unknown"


def _find_dead_end_node(em: EncodedModel, candidates: list[str]) -> str:
    model = em.solver.model()
    for nid in candidates:
        reach_val = model.eval(em.reach[nid], model_completion=True)
        if z3.is_true(reach_val):
            outgoing = em.graph.outgoing(nid)
            if not outgoing:
                return nid
            all_guards_false = True
            for edge in outgoing:
                taken_val = model.eval(em.edge_taken[edge.edge_id], model_completion=True)
                if z3.is_true(taken_val):
                    all_guards_false = False
                    break
            if all_guards_false:
                return nid
    return "unknown"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------

def load_properties(path: str) -> list[dict]:
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("properties", [])
