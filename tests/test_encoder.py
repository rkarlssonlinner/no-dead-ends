import z3

from ink_verify.story_graph import (
    BinOp, IntLit, NodeKind, StoryEdge, StoryGraph, StoryNode,
    VarDecl, VarRef, VarType,
)
from ink_verify.z3_encoder import encode


def _linear_graph():
    """A -> B -> C (all reachable)."""
    nodes = {
        "A": StoryNode("A", NodeKind.ENTRY),
        "B": StoryNode("B", NodeKind.KNOT),
        "C": StoryNode("C", NodeKind.TERMINAL),
    }
    edges = [StoryEdge("A", "B"), StoryEdge("B", "C")]
    return StoryGraph(nodes, edges, {}, "A")


def _isolated_node_graph():
    """A -> B, C isolated."""
    nodes = {
        "A": StoryNode("A", NodeKind.ENTRY),
        "B": StoryNode("B", NodeKind.KNOT),
        "C": StoryNode("C", NodeKind.KNOT),
    }
    edges = [StoryEdge("A", "B")]
    return StoryGraph(nodes, edges, {}, "A")


def _guarded_graph(initial_gold: int):
    """A -> B with guard gold >= 5."""
    nodes = {
        "A": StoryNode("A", NodeKind.ENTRY),
        "B": StoryNode("B", NodeKind.KNOT),
    }
    guard = BinOp(">=", VarRef("gold"), IntLit(5))
    edges = [StoryEdge("A", "B", guard=guard)]
    variables = {"gold": VarDecl("gold", VarType.INT, initial_gold)}
    return StoryGraph(nodes, edges, variables, "A")


def _mutation_graph():
    """A -> B with mutation gold := gold - 5, initial gold=10."""
    nodes = {
        "A": StoryNode("A", NodeKind.ENTRY),
        "B": StoryNode("B", NodeKind.KNOT),
    }
    mutation_expr = BinOp("-", VarRef("gold"), IntLit(5))
    edges = [StoryEdge("A", "B", mutations=[("gold", mutation_expr)])]
    variables = {"gold": VarDecl("gold", VarType.INT, 10)}
    return StoryGraph(nodes, edges, variables, "A")


def _choice_graph():
    """A -> B and A -> C (both choices, mutually exclusive)."""
    nodes = {
        "A": StoryNode("A", NodeKind.ENTRY),
        "B": StoryNode("B", NodeKind.KNOT),
        "C": StoryNode("C", NodeKind.KNOT),
    }
    edges = [
        StoryEdge("A", "B", choice_text="Go left"),
        StoryEdge("A", "C", choice_text="Go right"),
    ]
    return StoryGraph(nodes, edges, {}, "A")


class TestEntryReachable:
    def test_entry_always_reachable(self):
        em = encode(_linear_graph())
        em.solver.push()
        em.solver.add(em.reach["A"] == True)
        assert em.solver.check() == z3.sat
        em.solver.pop()


class TestLinearReachability:
    def test_all_reachable(self):
        em = encode(_linear_graph())
        for nid in ["A", "B", "C"]:
            em.solver.push()
            em.solver.add(em.reach[nid] == True)
            assert em.solver.check() == z3.sat, f"{nid} should be reachable"
            em.solver.pop()


class TestIsolatedNode:
    def test_unreachable(self):
        em = encode(_isolated_node_graph())
        em.solver.push()
        em.solver.add(em.reach["C"] == True)
        assert em.solver.check() == z3.unsat, "C should be unreachable"
        em.solver.pop()


class TestGuardedEdge:
    def test_guard_blocks(self):
        em = encode(_guarded_graph(initial_gold=3))
        em.solver.push()
        em.solver.add(em.reach["B"] == True)
        assert em.solver.check() == z3.unsat, "B should be unreachable with gold=3"
        em.solver.pop()

    def test_guard_allows(self):
        em = encode(_guarded_graph(initial_gold=10))
        em.solver.push()
        em.solver.add(em.reach["B"] == True)
        assert em.solver.check() == z3.sat, "B should be reachable with gold=10"
        em.solver.pop()


class TestMutation:
    def test_mutation_propagates(self):
        em = encode(_mutation_graph())
        em.solver.push()
        em.solver.add(em.reach["B"] == True)
        result = em.solver.check()
        assert result == z3.sat
        model = em.solver.model()
        gold_at_b = model.eval(em.node_vars["B"]["gold"])
        assert gold_at_b.as_long() == 5, f"gold at B should be 5, got {gold_at_b}"
        em.solver.pop()


class TestChoiceExclusivity:
    def test_not_both(self):
        em = encode(_choice_graph())
        em.solver.push()
        # Try to reach both B and C
        em.solver.add(em.reach["B"] == True)
        em.solver.add(em.reach["C"] == True)
        assert em.solver.check() == z3.unsat, "Cannot reach both B and C"
        em.solver.pop()

    def test_each_individually_reachable(self):
        em = encode(_choice_graph())
        for nid in ["B", "C"]:
            em.solver.push()
            em.solver.add(em.reach[nid] == True)
            assert em.solver.check() == z3.sat, f"{nid} should be reachable"
            em.solver.pop()


class TestInvariantEncoding:
    def test_invariant_holds(self):
        """gold starts 10, decremented by 3 on one edge. gold >= 0 always holds."""
        nodes = {
            "A": StoryNode("A", NodeKind.ENTRY),
            "B": StoryNode("B", NodeKind.TERMINAL),
        }
        mutation = BinOp("-", VarRef("gold"), IntLit(3))
        edges = [StoryEdge("A", "B", mutations=[("gold", mutation)])]
        variables = {"gold": VarDecl("gold", VarType.INT, 10)}
        g = StoryGraph(nodes, edges, variables, "A")
        em = encode(g)

        # Check if any reachable node has gold < 0
        violation = z3.Or(*[
            z3.And(em.reach[nid], em.node_vars[nid]["gold"] < 0)
            for nid in g.nodes
        ])
        em.solver.push()
        em.solver.add(violation)
        assert em.solver.check() == z3.unsat, "gold should never go negative"
        em.solver.pop()

    def test_invariant_violated(self):
        """gold starts 2, decremented by 3. gold >= 0 is violated."""
        nodes = {
            "A": StoryNode("A", NodeKind.ENTRY),
            "B": StoryNode("B", NodeKind.TERMINAL),
        }
        mutation = BinOp("-", VarRef("gold"), IntLit(3))
        edges = [StoryEdge("A", "B", mutations=[("gold", mutation)])]
        variables = {"gold": VarDecl("gold", VarType.INT, 2)}
        g = StoryGraph(nodes, edges, variables, "A")
        em = encode(g)

        violation = z3.Or(*[
            z3.And(em.reach[nid], em.node_vars[nid]["gold"] < 0)
            for nid in g.nodes
        ])
        em.solver.push()
        em.solver.add(violation)
        assert em.solver.check() == z3.sat, "gold goes negative — violation exists"
        em.solver.pop()
