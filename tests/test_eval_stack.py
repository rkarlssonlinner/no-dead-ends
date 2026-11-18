from ink_verify.ink_parser import EvalInterpreter
from ink_verify.story_graph import BinOp, IntLit, UnaryOp, VarRef, VisitCount


def _eval_sequence(items: list) -> object:
    interp = EvalInterpreter()
    for item in items:
        interp.feed(item)
    return interp.result()


class TestEvalInterpreter:
    def test_single_var_ref(self):
        result = _eval_sequence([{"VAR?": "x"}])
        assert result == VarRef("x")

    def test_binary_comparison(self):
        result = _eval_sequence([{"VAR?": "gold"}, 5, {">=": 2}])
        assert result == BinOp(">=", VarRef("gold"), IntLit(5))

    def test_compound_expression(self):
        result = _eval_sequence([{"VAR?": "a"}, {"VAR?": "b"}, {"+": 2}, 10, {"<": 2}])
        assert result == BinOp("<", BinOp("+", VarRef("a"), VarRef("b")), IntLit(10))

    def test_unary_not(self):
        result = _eval_sequence([{"VAR?": "flag"}, {"!": 1}])
        assert result == UnaryOp("!", VarRef("flag"))

    def test_duplicate(self):
        result = _eval_sequence([{"VAR?": "x"}, "du", {"*": 2}])
        assert result == BinOp("*", VarRef("x"), VarRef("x"))

    def test_visit_count(self):
        result = _eval_sequence([{"CNT?": "cave"}])
        assert result == VisitCount("cave")

    def test_arithmetic_then_compare(self):
        result = _eval_sequence([5, 3, {"+": 2}, {"VAR?": "y"}, {"==": 2}])
        assert result == BinOp("==", BinOp("+", IntLit(5), IntLit(3)), VarRef("y"))

    def test_unary_negate(self):
        result = _eval_sequence([{"VAR?": "x"}, {"_": 1}])
        assert result == UnaryOp("_", VarRef("x"))

    def test_logical_and(self):
        result = _eval_sequence([{"VAR?": "a"}, {"VAR?": "b"}, {"&&": 2}])
        assert result == BinOp("&&", VarRef("a"), VarRef("b"))

    def test_clear(self):
        interp = EvalInterpreter()
        interp.feed(5)
        interp.clear()
        assert interp.result() is None

    def test_empty_result(self):
        interp = EvalInterpreter()
        assert interp.result() is None
