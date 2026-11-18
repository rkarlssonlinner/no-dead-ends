import pytest
from pathlib import Path

from ink_verify.loader import load_story

STORIES = Path(__file__).parent / "stories"


class TestLoadInkJson:
    def test_load_linear(self):
        result = load_story(str(STORIES / "linear.ink.json"))
        assert "inkVersion" in result.json_data
        assert "root" in result.json_data

    def test_load_branching(self):
        result = load_story(str(STORIES / "branching.ink.json"))
        assert result.json_data["inkVersion"] == 19

    def test_load_variables(self):
        result = load_story(str(STORIES / "variables.ink.json"))
        assert "root" in result.json_data

    def test_has_source_when_ink_nearby(self):
        result = load_story(str(STORIES / "linear.ink.json"))
        assert result.has_source
        assert any(f.name == "linear.ink" for f in result.ink_files)


class TestLoadErrors:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_story("/nonexistent/path/story.ink.json")

    def test_not_ink_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"hello": "world"}')
        with pytest.raises(ValueError, match="Not a valid Ink JSON"):
            load_story(str(bad))
