from ink_verify.story_graph import (
    BinOp, BoolLit, IntLit, NodeKind, StoryEdge, StoryGraph, StoryNode,
    StringLit, UnaryOp, VarDecl, VarRef, VarType, VisitCount,
)


class TestSymExpr:
    def test_intlit_equality(self):
        assert IntLit(5) == IntLit(5)
        assert IntLit(5) != IntLit(6)

    def test_frozen_and_hashable(self):
        a = BinOp(">=", VarRef("gold"), IntLit(0))
        b = BinOp(">=", VarRef("gold"), IntLit(0))
        assert a == b
        assert hash(a) == hash(b)
        assert {a, b} == {a}

    def test_nested_expr(self):
        expr = BinOp("<", BinOp("+", VarRef("a"), VarRef("b")), IntLit(10))
        assert expr.op == "<"
        assert expr.left.op == "+"

    def test_unary_op(self):
        expr = UnaryOp("!", VarRef("flag"))
        assert expr.op == "!"
        assert expr.operand == VarRef("flag")

    def test_visit_count(self):
        v = VisitCount("cave")
        assert v.target == "cave"
        assert v == VisitCount("cave")

    def test_string_lit(self):
        s = StringLit("hello")
        assert s.value == "hello"

    def test_bool_lit(self):
        assert BoolLit(True) != BoolLit(False)


class TestVarDecl:
    def test_int_var(self):
        v = VarDecl("gold", VarType.INT, 10)
        assert v.var_type == VarType.INT
        assert v.initial_value == 10

    def test_bool_var(self):
        v = VarDecl("has_key", VarType.BOOL, False)
        assert v.var_type == VarType.BOOL


class TestStoryGraph:
    def _make_linear_graph(self):
        nodes = {
            "start": StoryNode("start", NodeKind.KNOT),
            "middle": StoryNode("middle", NodeKind.KNOT),
            "end": StoryNode("end", NodeKind.TERMINAL),
        }
        edges = [
            StoryEdge("start", "middle"),
            StoryEdge("middle", "end"),
        ]
        return StoryGraph(nodes, edges, {}, "start")

    def test_outgoing_incoming(self):
        g = self._make_linear_graph()
        assert len(g.outgoing("start")) == 1
        assert g.outgoing("start")[0].target == "middle"
        assert len(g.incoming("middle")) == 1
        assert g.incoming("middle")[0].source == "start"
        assert len(g.incoming("start")) == 0
        assert len(g.outgoing("end")) == 0

    def test_terminals(self):
        g = self._make_linear_graph()
        assert g.terminals() == ["end"]
        assert "start" in g.non_terminals()
        assert "middle" in g.non_terminals()

    def test_edge_ids_auto_assigned(self):
        g = self._make_linear_graph()
        assert g.edges[0].edge_id == "e_0"
        assert g.edges[1].edge_id == "e_1"

    def test_validate_clean(self):
        g = self._make_linear_graph()
        assert g.validate() == []

    def test_validate_dangling_target(self):
        nodes = {"a": StoryNode("a", NodeKind.KNOT)}
        edges = [StoryEdge("a", "nonexistent")]
        g = StoryGraph(nodes, edges, {}, "a")
        warnings = g.validate()
        assert any("nonexistent" in w for w in warnings)

    def test_validate_bad_entry(self):
        nodes = {"a": StoryNode("a", NodeKind.KNOT)}
        g = StoryGraph(nodes, [], {}, "missing")
        warnings = g.validate()
        assert any("missing" in w for w in warnings)

    def test_validate_dangling_source(self):
        nodes = {"b": StoryNode("b", NodeKind.KNOT)}
        edges = [StoryEdge("ghost", "b")]
        g = StoryGraph(nodes, edges, {}, "b")
        warnings = g.validate()
        assert any("ghost" in w for w in warnings)
