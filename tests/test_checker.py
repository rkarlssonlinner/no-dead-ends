import json
from pathlib import Path

from ink_verify.checker import (
    auto_detect_properties, check_properties, load_properties,
    parse_property_expr,
)
from ink_verify.ink_parser import parse_story
from ink_verify.story_graph import BinOp, BoolLit, IntLit, UnaryOp, VarRef

STORIES = Path(__file__).parent / "stories"
PROPS = Path(__file__).parent / "properties"


def _load_story(name: str):
    from ink_verify.source_index import build_source_index
    with open(STORIES / name) as f:
        json_data = json.load(f)
    ink_files = sorted(STORIES.glob("*.ink"))
    src_index = build_source_index(ink_files) if ink_files else None
    return parse_story(json_data, source_index=src_index)


class TestExpressionParser:
    def test_simple_comparison(self):
        result = parse_property_expr("gold >= 0")
        assert result == BinOp(">=", VarRef("gold"), IntLit(0))

    def test_boolean_and(self):
        result = parse_property_expr("gold > 0 and has_key == True")
        assert isinstance(result, BinOp)
        assert result.op == "&&"

    def test_not(self):
        result = parse_property_expr("not dead")
        assert result == UnaryOp("!", VarRef("dead"))

    def test_true_false(self):
        result = parse_property_expr("has_key == True")
        assert result == BinOp("==", VarRef("has_key"), BoolLit(True))


class TestLinearStoryChecks:
    def test_all_pass(self):
        g = _load_story("linear.ink.json")
        props = load_properties(str(PROPS / "linear.yaml"))
        verdicts = check_properties(g, props)
        for v in verdicts:
            assert v.passed, f"'{v.name}' should pass: {v.reason}"

    def test_auto_detect(self):
        g = _load_story("linear.ink.json")
        props = auto_detect_properties(g)
        verdicts = check_properties(g, props)
        # All knots should be reachable, no dead ends
        for v in verdicts:
            assert v.passed, f"'{v.name}' should pass: {v.reason}"


class TestVariablesStoryChecks:
    def test_gold_non_negative(self):
        g = _load_story("variables.ink.json")
        props = [{"name": "gold >= 0", "type": "invariant", "expr": "gold >= 0"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed, "gold should stay non-negative in variables story"

    def test_cave_reachable(self):
        g = _load_story("variables.ink.json")
        props = [{"name": "cave reachable", "type": "reachable", "knot": "cave"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed


class TestDeadEndStoryChecks:
    def test_dead_end_detected(self):
        g = _load_story("dead_end.ink.json")
        props = [{"name": "no dead ends", "type": "no_dead_ends"}]
        verdicts = check_properties(g, props)
        assert not verdicts[0].passed, "Should detect dead end"
        assert "stuck" in verdicts[0].reason

    def test_ending_unreachable(self):
        g = _load_story("dead_end.ink.json")
        props = [{"name": "ending reachable", "type": "reachable", "knot": "ending"}]
        verdicts = check_properties(g, props)
        assert not verdicts[0].passed, "ending should be unreachable"

    def test_counterexample_has_path(self):
        g = _load_story("dead_end.ink.json")
        props = [{"name": "no dead ends", "type": "no_dead_ends"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].counterexample is not None
        assert len(verdicts[0].counterexample) >= 1
        path_nodes = [s.node_id for s in verdicts[0].counterexample]
        assert "start" in path_nodes


class TestLoopStoryChecks:
    def test_fallback_reachable(self):
        g = _load_story("loop.ink.json")
        props = [{"name": "fallback reachable", "type": "reachable", "knot": "fallback"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed

    def test_no_dead_ends(self):
        g = _load_story("loop.ink.json")
        props = [{"name": "no dead ends", "type": "no_dead_ends"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed


class TestTunnelStoryChecks:
    def test_after_tunnel_reachable(self):
        g = _load_story("tunnel.ink.json")
        props = [{"name": "after_tunnel reachable", "type": "reachable", "knot": "after_tunnel"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed

    def test_crossing_reachable(self):
        g = _load_story("tunnel.ink.json")
        props = [{"name": "crossing reachable", "type": "reachable", "knot": "crossing"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed

    def test_no_dead_ends(self):
        g = _load_story("tunnel.ink.json")
        props = [{"name": "no dead ends", "type": "no_dead_ends"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed


class TestBranchingStoryChecks:
    def test_reachable_pass(self):
        g = _load_story("branching.ink.json")
        props = [
            {"name": "path_a reachable", "type": "reachable", "knot": "path_a"},
            {"name": "path_b reachable", "type": "reachable", "knot": "path_b"},
        ]
        verdicts = check_properties(g, props)
        for v in verdicts:
            assert v.passed, f"'{v.name}' should pass: {v.reason}"

    def test_nonexistent_fails(self):
        g = _load_story("branching.ink.json")
        props = [{"name": "nope reachable", "type": "reachable", "knot": "nope"}]
        verdicts = check_properties(g, props)
        assert not verdicts[0].passed

    def test_no_dead_ends(self):
        g = _load_story("branching.ink.json")
        props = [{"name": "no dead ends", "type": "no_dead_ends"}]
        verdicts = check_properties(g, props)
        assert verdicts[0].passed

    def test_full_yaml(self):
        g = _load_story("branching.ink.json")
        props = load_properties(str(PROPS / "branching.yaml"))
        verdicts = check_properties(g, props)
        passed = [v for v in verdicts if v.passed]
        failed = [v for v in verdicts if not v.passed]
        assert len(passed) == 3, f"Expected 3 passed, got {len(passed)}"
        assert len(failed) == 1, f"Expected 1 failed, got {len(failed)}"
        assert failed[0].name == "nonexistent reachable"
