from __future__ import annotations

import json
import sys

import click

from ink_verify.checker import (
    Verdict, auto_detect_properties, check_properties, load_properties,
)
from ink_verify.ink_parser import parse_story
from ink_verify.loader import load_story


@click.command()
@click.argument("story_path")
@click.option("--properties", "-p", default=None, help="YAML properties file")
@click.option("--bound", "-b", default=3, type=int, help="Visit count bound (default: 3)")
@click.option("--json-output", "--json", "json_out", is_flag=True, help="JSON output for tools")
@click.option("--verbose", "-v", is_flag=True, help="Show details")
def main(story_path: str, properties: str | None, bound: int, json_out: bool, verbose: bool):
    """Formally verify properties of an Ink story using Z3."""
    try:
        json_data = load_story(story_path)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        if json_out:
            click.echo(json.dumps({"error": str(e)}))
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    graph = parse_story(json_data)

    if properties:
        props = load_properties(properties)
    else:
        props = auto_detect_properties(graph)

    verdicts = check_properties(graph, props, bound)

    if json_out:
        _output_json(story_path, graph, verdicts)
    else:
        _output_human(story_path, graph, verdicts, verbose)

    if any(not v.passed for v in verdicts):
        sys.exit(1)


def _output_human(path: str, graph, verdicts: list[Verdict], verbose: bool):
    knot_count = len([n for n in graph.nodes.values()
                      if n.kind.value in ("knot", "stitch")])
    var_count = len(graph.variables)
    click.echo(f"ink-verify — {path} ({knot_count} knots, {var_count} variables)")
    click.echo()

    passed = 0
    failed = 0
    for v in verdicts:
        if v.passed:
            click.echo(f"  [PASS] {v.name}")
            passed += 1
        else:
            click.echo(f"  [FAIL] {v.name}")
            if v.reason:
                click.echo(f"         {v.reason}")
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


def _output_json(path: str, graph, verdicts: list[Verdict]):
    knot_count = len([n for n in graph.nodes.values()
                      if n.kind.value in ("knot", "stitch")])
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
        results.append(entry)

    output = {
        "story": path,
        "knots": knot_count,
        "variables": list(graph.variables.keys()),
        "results": results,
    }
    click.echo(json.dumps(output, indent=2))
