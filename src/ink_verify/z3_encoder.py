from __future__ import annotations

from dataclasses import dataclass, field

import z3

from ink_verify.story_graph import (
    BinOp, BoolLit, IntLit, NodeKind, StoryEdge, StoryGraph,
    StringLit, SymExpr, UnaryOp, VarDecl, VarRef, VarType, VisitCount,
)


@dataclass
class EncodedModel:
    solver: z3.Solver
    graph: StoryGraph
    reach: dict[str, z3.BoolRef]
    node_vars: dict[str, dict[str, z3.ExprRef]]
    edge_taken: dict[str, z3.BoolRef]
    edge_index: dict[str, StoryEdge]


def encode(graph: StoryGraph, bound: int = 3) -> EncodedModel:
    """Encode a StoryGraph as Z3 constraints (single-witness-path model)."""
    solver = z3.Solver()

    reach: dict[str, z3.BoolRef] = {}
    node_vars: dict[str, dict[str, z3.ExprRef]] = {}
    edge_taken: dict[str, z3.BoolRef] = {}
    edge_index: dict[str, StoryEdge] = {}

    # Filter out string variables — Z3 can't encode them meaningfully
    encodable_vars = {k: v for k, v in graph.variables.items() if v.var_type != VarType.STRING}

    # Create Z3 variables for each node
    for nid in graph.nodes:
        reach[nid] = z3.Bool(f"reach_{nid}")
        node_vars[nid] = {}
        for vname, vdecl in encodable_vars.items():
            node_vars[nid][vname] = _make_z3_var(vdecl, nid)

    # Create Z3 variables for each edge
    for edge in graph.edges:
        edge_taken[edge.edge_id] = z3.Bool(f"taken_{edge.edge_id}")
        edge_index[edge.edge_id] = edge

    # --- Constraint 1: Entry node is reachable with initial values ---
    entry = graph.entry_node
    solver.add(reach[entry] == True)
    for vname, vdecl in encodable_vars.items():
        solver.add(node_vars[entry][vname] == _initial_z3_val(vdecl))

    # --- Constraint 2: Non-entry unreachable unless justified ---
    for nid in graph.nodes:
        if nid == entry:
            continue
        incoming = graph.incoming(nid)
        if incoming:
            solver.add(reach[nid] == z3.Or(*[edge_taken[e.edge_id] for e in incoming]))
        else:
            solver.add(reach[nid] == False)

    # --- Constraint 3: Edge semantics ---
    for edge in graph.edges:
        et = edge_taken[edge.edge_id]

        # Can only take edge if source is reachable
        solver.add(z3.Implies(et, reach[edge.source]))

        # Guard must hold (if present)
        if edge.guard is not None and edge.source in node_vars:
            try:
                guard_z3 = sym_to_z3(edge.guard, node_vars[edge.source])
                solver.add(z3.Implies(et, _coerce_bool(guard_z3)))
            except (ValueError, z3.Z3Exception):
                pass  # Guard references unsupported types (strings) — overapproximate as True

    # --- Constraint 4: At most one incoming edge taken per node ---
    for nid in graph.nodes:
        incoming = graph.incoming(nid)
        if len(incoming) > 1:
            solver.add(z3.AtMost(*[edge_taken[e.edge_id] for e in incoming], 1))

    # --- Constraint 5: Choice exclusivity (at most one choice per node) ---
    for nid in graph.nodes:
        outgoing = graph.outgoing(nid)
        choice_edges = [e for e in outgoing if e.choice_text or e.once_only or e.is_fallback]
        if len(choice_edges) > 1:
            solver.add(z3.AtMost(*[edge_taken[e.edge_id] for e in choice_edges], 1))

    # --- Constraint 6: Variable propagation ---
    for nid in graph.nodes:
        if nid == entry:
            continue
        incoming = graph.incoming(nid)
        if not incoming:
            continue

        for vname in encodable_vars:
            # Build ITE chain: if edge_1 taken, use its value; else if edge_2, ...
            try:
                val_expr = _initial_z3_val(encodable_vars[vname])
                for edge in reversed(incoming):
                    edge_val = _compute_edge_val(edge, vname, node_vars, encodable_vars)
                    val_expr = z3.If(edge_taken[edge.edge_id], edge_val, val_expr)
                solver.add(z3.Implies(reach[nid], node_vars[nid][vname] == val_expr))
            except (ValueError, z3.Z3Exception):
                pass  # Mutation references unsupported types — skip propagation

    return EncodedModel(solver, graph, reach, node_vars, edge_taken, edge_index)


def sym_to_z3(expr: SymExpr, var_map: dict[str, z3.ExprRef]) -> z3.ExprRef:
    """Convert a SymExpr to a Z3 expression."""
    if isinstance(expr, IntLit):
        return z3.IntVal(expr.value)
    elif isinstance(expr, BoolLit):
        return z3.BoolVal(expr.value)
    elif isinstance(expr, VarRef):
        if expr.name in var_map:
            return var_map[expr.name]
        return z3.BoolVal(True)  # Unknown var (likely string) — overapproximate
    elif isinstance(expr, VisitCount):
        key = f"__visit_{expr.target}"
        if key in var_map:
            return var_map[key]
        return z3.IntVal(0)
    elif isinstance(expr, BinOp):
        left = sym_to_z3(expr.left, var_map)
        right = sym_to_z3(expr.right, var_map)
        return _apply_binop(expr.op, left, right)
    elif isinstance(expr, UnaryOp):
        operand = sym_to_z3(expr.operand, var_map)
        if expr.op == "!":
            return z3.Not(_coerce_bool(operand))
        elif expr.op == "_":
            return -_coerce_int(operand)
    elif isinstance(expr, StringLit):
        return z3.StringVal(expr.value)
    raise ValueError(f"Cannot convert {type(expr).__name__} to Z3")


def _apply_binop(op: str, left: z3.ExprRef, right: z3.ExprRef) -> z3.ExprRef:
    if op == "+":
        return _coerce_int(left) + _coerce_int(right)
    elif op == "-":
        return _coerce_int(left) - _coerce_int(right)
    elif op == "*":
        return _coerce_int(left) * _coerce_int(right)
    elif op == "/":
        return _coerce_int(left) / _coerce_int(right)
    elif op == "%":
        return _coerce_int(left) % _coerce_int(right)
    elif op == "==":
        return left == right
    elif op == "!=":
        return left != right
    elif op == "<":
        return _coerce_int(left) < _coerce_int(right)
    elif op == ">":
        return _coerce_int(left) > _coerce_int(right)
    elif op == "<=":
        return _coerce_int(left) <= _coerce_int(right)
    elif op == ">=":
        return _coerce_int(left) >= _coerce_int(right)
    elif op == "&&":
        return z3.And(_coerce_bool(left), _coerce_bool(right))
    elif op == "||":
        return z3.Or(_coerce_bool(left), _coerce_bool(right))
    elif op == "MIN":
        l, r = _coerce_int(left), _coerce_int(right)
        return z3.If(l < r, l, r)
    elif op == "MAX":
        l, r = _coerce_int(left), _coerce_int(right)
        return z3.If(l > r, l, r)
    raise ValueError(f"Unknown binary operator: {op}")


def _coerce_bool(expr: z3.ExprRef) -> z3.BoolRef:
    """Ink treats nonzero ints as true."""
    if isinstance(expr, z3.BoolRef):
        return expr
    return expr != z3.IntVal(0)


def _coerce_int(expr: z3.ExprRef) -> z3.ArithRef:
    """Convert bool to int if needed."""
    if isinstance(expr, z3.BoolRef):
        return z3.If(expr, z3.IntVal(1), z3.IntVal(0))
    return expr


def _make_z3_var(vdecl: VarDecl, node_id: str) -> z3.ExprRef:
    name = f"{node_id}__{vdecl.name}"
    if vdecl.var_type == VarType.BOOL:
        return z3.Bool(name)
    return z3.Int(name)


def _initial_z3_val(vdecl: VarDecl) -> z3.ExprRef:
    if vdecl.var_type == VarType.BOOL:
        return z3.BoolVal(vdecl.initial_value)
    return z3.IntVal(vdecl.initial_value)


def _compute_edge_val(
    edge: StoryEdge,
    vname: str,
    node_vars: dict[str, dict[str, z3.ExprRef]],
    variables: dict[str, VarDecl],
) -> z3.ExprRef:
    """Compute the value of variable `vname` after taking `edge`."""
    for mut_name, mut_expr in edge.mutations:
        if mut_name == vname:
            return sym_to_z3(mut_expr, node_vars[edge.source])
    # Frame condition: variable unchanged
    if edge.source in node_vars and vname in node_vars[edge.source]:
        return node_vars[edge.source][vname]
    return _initial_z3_val(variables[vname])
