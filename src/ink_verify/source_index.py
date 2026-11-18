"""Scan .ink source files for variable types, knot locations, and mutation sites.

No Ink parser — just line-level regex. Used to correct the compiled JSON's
lossy type inference and to add file:line references to error output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ink_verify.story_graph import VarType


@dataclass
class VarInfo:
    name: str
    var_type: VarType
    initial_value: str
    file: str
    line: int


@dataclass
class KnotInfo:
    name: str
    file: str
    line: int


@dataclass
class MutationSite:
    variable: str
    file: str
    line: int
    text: str


@dataclass
class SourceIndex:
    variables: dict[str, VarInfo] = field(default_factory=dict)
    knots: dict[str, KnotInfo] = field(default_factory=dict)
    mutations: dict[str, list[MutationSite]] = field(default_factory=dict)
    list_names: set[str] = field(default_factory=set)
    list_values: set[str] = field(default_factory=set)
    functions: set[str] = field(default_factory=set)

    def var_type(self, name: str) -> VarType | None:
        info = self.variables.get(name)
        return info.var_type if info else None

    def knot_location(self, name: str) -> str:
        info = self.knots.get(name)
        if info:
            return f"{info.file}:{info.line}"
        return ""

    def mutation_locations(self, variable: str) -> list[str]:
        sites = self.mutations.get(variable, [])
        return [f"{s.file}:{s.line}  {s.text}" for s in sites]


_VAR_DECL = re.compile(r"^\s*VAR\s+(\w+)\s*=\s*(.+)$")
_LIST_DECL = re.compile(r"^\s*LIST\s+(\w+)\s*=")
_KNOT = re.compile(r"^={2,}\s*(?:function\s+)?(\w+)(?:\s*\(.*\))?\s*={0,}$")
_FUNC_KNOT = re.compile(r"^={2,}\s*function\s+(\w+)")
_STITCH = re.compile(r"^=\s+(\w+)(?:\s*\(.*\))?\s*$")
_MUTATION = re.compile(r"^\s*~\s*(\w+)\s*([+\-*/]?=)\s*(.+)$")
_MUTATION_INC = re.compile(r"^\s*~\s*(\w+)(\+\+|--)$")


def build_source_index(ink_files: list[Path]) -> SourceIndex:
    index = SourceIndex()
    current_knot = ""

    for path in ink_files:
        rel = path.name
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue

            m = _LIST_DECL.match(stripped)
            if m:
                list_name = m.group(1)
                index.list_names.add(list_name)
                # Extract list values: LIST Foo = val1, val2, (val3)
                after_eq = stripped.split("=", 1)[1] if "=" in stripped else ""
                for val in after_eq.split(","):
                    val = val.strip().strip("()")
                    if val and val.isidentifier():
                        index.list_values.add(val)
                continue

            m = _VAR_DECL.match(stripped)
            if m:
                name, val_str = m.group(1), m.group(2).strip()
                vtype = _infer_type(val_str, index.list_values)
                index.variables[name] = VarInfo(name, vtype, val_str, rel, lineno)
                continue

            m = _FUNC_KNOT.match(stripped)
            if m:
                index.functions.add(m.group(1))

            m = _KNOT.match(stripped)
            if m:
                current_knot = m.group(1)
                index.knots[current_knot] = KnotInfo(current_knot, rel, lineno)
                continue

            m = _STITCH.match(stripped)
            if m:
                stitch = m.group(1)
                full_name = f"{current_knot}.{stitch}" if current_knot else stitch
                index.knots[full_name] = KnotInfo(full_name, rel, lineno)
                continue

            m = _MUTATION.match(stripped)
            if m:
                vname = m.group(1)
                index.mutations.setdefault(vname, []).append(
                    MutationSite(vname, rel, lineno, stripped))
                continue

            m = _MUTATION_INC.match(stripped)
            if m:
                vname = m.group(1)
                index.mutations.setdefault(vname, []).append(
                    MutationSite(vname, rel, lineno, stripped))

    return index


def _infer_type(val_str: str, known_list_values: set[str] | None = None) -> VarType:
    val = val_str.rstrip().rstrip(";").strip()
    if val.startswith('"') or val.startswith("'"):
        return VarType.STRING
    if val in ("true", "false"):
        return VarType.BOOL
    if val.startswith("->"):
        return VarType.STRING  # divert target — not numeric
    if val in ("NONE", "none"):
        return VarType.STRING  # LIST empty value — not numeric
    if val.startswith("(") and val.endswith(")"):
        return VarType.STRING  # LIST multi-value — not numeric
    if known_list_values and val in known_list_values:
        return VarType.STRING  # known LIST value — not numeric
    try:
        int(val)
        return VarType.INT
    except ValueError:
        pass
    try:
        float(val)
        return VarType.INT
    except ValueError:
        pass
    # Uppercase identifier likely a CONST or LIST value
    if val.isidentifier() and val[0].isupper():
        return VarType.STRING
    return VarType.INT
