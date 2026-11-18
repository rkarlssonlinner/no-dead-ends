from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ink_verify.checker import (
    Verdict, auto_detect_properties, check_properties, load_properties,
)
from ink_verify.ink_parser import parse_story
from ink_verify.loader import load_story
from ink_verify.source_index import SourceIndex, build_source_index


def _find_ink_files(path: str) -> list[Path]:
    """Find .ink files from a path (directory, .otproject, or alongside a .json)."""
    p = Path(path)
    if p.is_dir():
        return sorted(p.glob("**/*.ink"))
    if p.suffix == ".otproject":
        import tempfile, zipfile
        tmpdir = tempfile.mkdtemp()
        files = []
        with zipfile.ZipFile(p) as zf:
            for name in zf.namelist():
                if name.endswith(".ink"):
                    target = Path(tmpdir) / Path(name).name
                    with zf.open(name) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    files.append(target)
        return files
    # For .json or .tale, look for .ink files next to it or in a story/ subdir
    candidates = []
    if p.parent.exists():
        candidates.extend(p.parent.glob("*.ink"))
        story_dir = p.parent / "story"
        if story_dir.is_dir():
            candidates.extend(story_dir.glob("**/*.ink"))
    return sorted(set(candidates))


@click.command()
@click.argument("story_path")
@click.option("--source", "-s", default=None,
              help="Path to .ink source (directory, .otproject, or single .ink file)")
@click.option("--properties", "-p", default=None, help="YAML properties file")
@click.option("--bound", "-b", default=3, type=int, help="Visit count bound (default: 3)")
@click.option("--json-output", "--json", "json_out", is_flag=True, help="JSON output for tools")
@click.option("--verbose", "-v", is_flag=True, help="Show details")
def main(story_path: str, source: str | None, properties: str | None,
         bound: int, json_out: bool, verbose: bool):
    """Formally verify properties of an Ink story using Z3."""
    try:
        result = load_story(story_path)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        if json_out:
            click.echo(json.dumps({"error": str(e)}))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    # Build source index from .ink files
    src_index: SourceIndex | None = None
    if source:
        ink_files = _find_ink_files(source)
        if ink_files:
            src_index = build_source_index(ink_files)
    elif result.has_source:
        src_index = build_source_index(result.ink_files)

    if src_index is None:
        if not json_out:
            click.echo("Warning: no .ink source found — variable types inferred from compiled JSON", err=True)
            click.echo("         Use --source <dir> to provide .ink files for accurate results", err=True)
            click.echo("", err=True)

    graph = parse_story(result.json_data, source_index=src_index)

    if properties:
        props = load_properties(properties)
    else:
        props = auto_detect_properties(graph, source_index=src_index)

    verdicts = check_properties(graph, props, bound)

    if json_out:
        _output_json(story_path, graph, verdicts, src_index)
    else:
        _output_human(story_path, graph, verdicts, verbose, src_index)

    if any(not v.passed for v in verdicts):
        sys.exit(1)


def _output_human(path: str, graph, verdicts: list[Verdict], verbose: bool,
                   src_index: SourceIndex | None):
    knot_count = len([n for n in graph.nodes.values()
                      if n.kind.value in ("knot", "stitch")])
    var_count = len(graph.variables)
    dropped = getattr(graph, "_dropped_edges", 0)
    total_edges = len(graph.edges) + dropped
    src_label = " + source" if src_index else ""

    click.echo(f"ink-verify — {path} ({knot_count} knots, {var_count} variables{src_label})")
    if dropped:
        pct = len(graph.edges) / total_edges * 100 if total_edges else 100
        click.echo(f"  coverage: {pct:.0f}% of edges resolved ({dropped} unresolved — results may be incomplete)")
    click.echo()

    passed = 0
    failed = 0
    for v in verdicts:
        if v.property_type == "_info":
            click.echo(f"  [INFO] {v.reason}")
            continue
        if v.passed:
            click.echo(f"  [PASS] {v.name}")
            passed += 1
        else:
            click.echo(f"  [FAIL] {v.name}")
            if v.reason:
                click.echo(f"         {v.reason}")
            # Show source location if available
            if src_index and "violated at" in v.reason:
                knot = v.reason.split("'")[1] if "'" in v.reason else ""
                loc = src_index.knot_location(knot)
                if loc:
                    click.echo(f"         source: {loc}")
                # Show mutation sites for the variable
                var_name = v.name.split(" ")[0] if v.name else ""
                sites = src_index.mutation_locations(var_name)
                if sites:
                    click.echo(f"         mutations:")
                    for s in sites[:5]:
                        click.echo(f"           {s}")
            if v.counterexample and verbose:
                click.echo("         Path:")
                for step in v.counterexample:
                    line = f"           {step.node_id}"
                    if step.choice_text:
                        line += f' -> "{step.choice_text}"'
                    if step.variables:
                        vals = ", ".join(f"{k}={v}" for k, v in step.variables.items())
                        line += f"  ({vals})"
                    click.echo(line)
            failed += 1

    click.echo()
    click.echo(f"{passed} passed, {failed} failed")


def _output_json(path: str, graph, verdicts: list[Verdict],
                  src_index: SourceIndex | None):
    knot_count = len([n for n in graph.nodes.values()
                      if n.kind.value in ("knot", "stitch")])
    dropped = getattr(graph, "_dropped_edges", 0)
    total_edges = len(graph.edges) + dropped
    coverage = len(graph.edges) / total_edges * 100 if total_edges else 100

    results = []
    for v in verdicts:
        entry = {
            "name": v.name,
            "type": v.property_type,
            "passed": v.passed,
        }
        if not v.passed:
            entry["reason"] = v.reason
            if v.counterexample:
                entry["counterexample"] = {
                    "path": [s.node_id for s in v.counterexample],
                    "choices": [s.choice_text for s in v.counterexample if s.choice_text],
                    "variables_at_violation": v.counterexample[-1].variables if v.counterexample else {},
                }
            # Add source locations
            if src_index:
                if "violated at" in v.reason and "'" in v.reason:
                    knot = v.reason.split("'")[1]
                    loc = src_index.knot_location(knot)
                    if loc:
                        entry["source_location"] = loc
                var_name = v.name.split(" ")[0] if v.name else ""
                sites = src_index.mutation_locations(var_name)
                if sites:
                    entry["mutation_sites"] = sites
        results.append(entry)

    output = {
        "story": path,
        "knots": knot_count,
        "variables": list(graph.variables.keys()),
        "has_source": src_index is not None,
        "coverage": round(coverage, 1),
        "edges_resolved": len(graph.edges),
        "edges_dropped": dropped,
        "results": results,
    }
    click.echo(json.dumps(output, indent=2))
