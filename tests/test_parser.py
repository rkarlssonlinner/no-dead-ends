import json
from pathlib import Path

from ink_verify.ink_parser import parse_story
from ink_verify.story_graph import NodeKind

STORIES = Path(__file__).parent / "stories"


def _load(name: str) -> dict:
    with open(STORIES / name) as f:
        return json.load(f)


class TestLinearStory:
    def test_node_count(self):
        g = parse_story(_load("linear.ink.json"))
        knots = [n for n in g.nodes.values() if n.kind == NodeKind.KNOT]
        assert len(knots) == 3, f"Expected 3 knots, got {len(knots)}: {[k.id for k in knots]}"

    def test_entry_node(self):
        g = parse_story(_load("linear.ink.json"))
        assert g.entry_node == "start"

    def test_edges(self):
        g = parse_story(_load("linear.ink.json"))
        targets_from_start = [e.target for e in g.outgoing("start")]
        assert "middle" in targets_from_start

        targets_from_middle = [e.target for e in g.outgoing("middle")]
        assert "ending" in targets_from_middle

    def test_terminal(self):
        g = parse_story(_load("linear.ink.json"))
        terminals = g.terminals()
        assert len(terminals) >= 1

    def test_ending_reaches_terminal(self):
        g = parse_story(_load("linear.ink.json"))
        targets_from_ending = [e.target for e in g.outgoing("ending")]
        assert any(g.nodes[t].kind == NodeKind.TERMINAL for t in targets_from_ending if t in g.nodes)

    def test_no_guards(self):
        g = parse_story(_load("linear.ink.json"))
        for e in g.edges:
            assert e.guard is None, f"Edge {e.source}->{e.target} has unexpected guard"

    def test_validate_clean(self):
        g = parse_story(_load("linear.ink.json"))
        assert g.validate() == []


class TestVariablesStory:
    def test_variables_declared(self):
        g = parse_story(_load("variables.ink.json"))
        assert "gold" in g.variables
        assert "has_key" in g.variables
        assert g.variables["gold"].initial_value == 10

    def test_knots_present(self):
        g = parse_story(_load("variables.ink.json"))
        knot_ids = {n.id for n in g.nodes.values() if n.kind == NodeKind.KNOT}
        assert "start" in knot_ids
        assert "shop" in knot_ids
        assert "cave" in knot_ids
        assert "ending" in knot_ids

    def test_choice_has_mutation(self):
        g = parse_story(_load("variables.ink.json"))
        # The "Buy a sword" edge from start should mutate gold
        sword_edges = [e for e in g.outgoing("start") if "shop" in e.target]
        assert any(len(e.mutations) > 0 for e in sword_edges), \
            f"Expected mutation on sword edge, got mutations: {[e.mutations for e in sword_edges]}"

    def test_conditional_choice_has_guard(self):
        g = parse_story(_load("variables.ink.json"))
        # Shop's "Buy a potion" edge should have a guard (gold >= 5)
        shop_edges = g.outgoing("shop")
        guarded = [e for e in shop_edges if e.guard is not None]
        assert len(guarded) >= 1, f"Expected guarded edges from shop, got {len(guarded)}"


class TestDeadEndStory:
    def test_variables_declared(self):
        g = parse_story(_load("dead_end.ink.json"))
        assert "gold" in g.variables
        assert g.variables["gold"].initial_value == 3

    def test_stuck_node_has_guarded_edges(self):
        g = parse_story(_load("dead_end.ink.json"))
        stuck_edges = g.outgoing("stuck")
        guarded = [e for e in stuck_edges if e.guard is not None]
        assert len(guarded) >= 1, "Expected guarded edges from stuck"

    def test_choice_has_mutation(self):
        g = parse_story(_load("dead_end.ink.json"))
        start_edges = g.outgoing("start")
        mutating = [e for e in start_edges if len(e.mutations) > 0]
        assert len(mutating) >= 1, "Expected mutations on start choices"


class TestLoopStory:
    def test_hub_node_exists(self):
        g = parse_story(_load("loop.ink.json"))
        assert "hub" in g.nodes

    def test_fallback_reachable(self):
        g = parse_story(_load("loop.ink.json"))
        assert "fallback" in g.nodes

    def test_has_once_only_choices(self):
        g = parse_story(_load("loop.ink.json"))
        once_only = [e for e in g.edges if e.once_only]
        assert len(once_only) >= 3, f"Expected at least 3 once-only choices, got {len(once_only)}"

    def test_has_fallback_choice(self):
        g = parse_story(_load("loop.ink.json"))
        fallbacks = [e for e in g.edges if e.is_fallback]
        assert len(fallbacks) >= 1, "Expected a fallback choice"


class TestTunnelStory:
    def test_all_knots_present(self):
        g = parse_story(_load("tunnel.ink.json"))
        knot_ids = {n.id for n in g.nodes.values() if n.kind == NodeKind.KNOT}
        assert "start" in knot_ids
        assert "crossing" in knot_ids
        assert "after_tunnel" in knot_ids

    def test_crossing_reachable_from_start(self):
        g = parse_story(_load("tunnel.ink.json"))
        targets_from_start = {e.target for e in g.outgoing("start")}
        assert "crossing" in targets_from_start

    def test_validate_clean(self):
        g = parse_story(_load("tunnel.ink.json"))
        warnings = g.validate()
        assert warnings == [], f"Unexpected warnings: {warnings}"


class TestBranchingStory:
    def test_node_count(self):
        g = parse_story(_load("branching.ink.json"))
        knots = [n for n in g.nodes.values() if n.kind == NodeKind.KNOT]
        knot_names = {k.id for k in knots}
        assert "start" in knot_names
        assert "path_a" in knot_names
        assert "path_b" in knot_names
        assert "merge" in knot_names

    def test_choice_edges_from_start(self):
        g = parse_story(_load("branching.ink.json"))
        outgoing = g.outgoing("start")
        targets = {e.target for e in outgoing}
        assert "path_a" in targets, f"Expected path_a in targets, got {targets}"
        assert "path_b" in targets, f"Expected path_b in targets, got {targets}"

    def test_choices_are_once_only(self):
        g = parse_story(_load("branching.ink.json"))
        choice_edges = [e for e in g.outgoing("start") if e.target in ("path_a", "path_b")]
        for e in choice_edges:
            assert e.once_only, f"Edge to {e.target} should be once-only"

    def test_both_paths_reach_merge(self):
        g = parse_story(_load("branching.ink.json"))
        from_a = {e.target for e in g.outgoing("path_a")}
        from_b = {e.target for e in g.outgoing("path_b")}
        assert "merge" in from_a
        assert "merge" in from_b

    def test_merge_reaches_terminal(self):
        g = parse_story(_load("branching.ink.json"))
        from_merge = [e.target for e in g.outgoing("merge")]
        assert any(g.nodes[t].kind == NodeKind.TERMINAL for t in from_merge if t in g.nodes)

    def test_validate_clean(self):
        g = parse_story(_load("branching.ink.json"))
        assert g.validate() == []
