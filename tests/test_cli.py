import json
from pathlib import Path

from click.testing import CliRunner

from ink_verify.cli import main

STORIES = Path(__file__).parent / "stories"
PROPS = Path(__file__).parent / "properties"


def _invoke(*args):
    runner = CliRunner()
    return runner.invoke(main, list(args), catch_exceptions=False)


class TestAutoDetectAllPass:
    def test_exit_code_zero(self):
        result = _invoke(str(STORIES / "linear.ink.json"))
        assert result.exit_code == 0

    def test_output_contains_pass(self):
        result = _invoke(str(STORIES / "linear.ink.json"))
        assert "[PASS]" in result.output
        assert "[FAIL]" not in result.output


class TestAutoDetectWithFailure:
    def test_exit_code_one(self):
        result = _invoke(str(STORIES / "dead_end.ink.json"))
        assert result.exit_code == 1

    def test_output_contains_fail(self):
        result = _invoke(str(STORIES / "dead_end.ink.json"))
        assert "[FAIL]" in result.output


class TestJsonOutput:
    def test_valid_json(self):
        result = _invoke(str(STORIES / "linear.ink.json"), "--json")
        data = json.loads(result.output)
        assert "results" in data

    def test_all_passed(self):
        result = _invoke(str(STORIES / "linear.ink.json"), "--json")
        data = json.loads(result.output)
        assert all(r["passed"] for r in data["results"])

    def test_has_story_field(self):
        result = _invoke(str(STORIES / "linear.ink.json"), "--json")
        data = json.loads(result.output)
        assert "story" in data
        assert "knots" in data
        assert "variables" in data


class TestCustomProperties:
    def test_branching_yaml_exit_code(self):
        result = _invoke(
            str(STORIES / "branching.ink.json"),
            "--properties", str(PROPS / "branching.yaml"),
        )
        assert result.exit_code == 1

    def test_branching_yaml_output(self):
        result = _invoke(
            str(STORIES / "branching.ink.json"),
            "--properties", str(PROPS / "branching.yaml"),
        )
        assert "nope" in result.output.lower() or "nonexistent" in result.output.lower()


class TestBadFile:
    def test_exit_code_two(self):
        result = _invoke("/tmp/no_such_file_at_all.ink.json")
        assert result.exit_code == 2
