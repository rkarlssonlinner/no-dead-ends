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
_KNOT = re.compile(r"^={2,}\s*(?:function\s+)?(\w+)(?:\s*\(.*\))?\s*={0,}$")
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

            m = _VAR_DECL.match(stripped)
            if m:
                name, val_str = m.group(1), m.group(2).strip()
                vtype = _infer_type(val_str)
                index.variables[name] = VarInfo(name, vtype, val_str, rel, lineno)
                continue

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


def _infer_type(val_str: str) -> VarType:
    val = val_str.rstrip().rstrip(";").strip()
    if val.startswith('"') or val.startswith("'"):
        return VarType.STRING
    if val in ("true", "false"):
        return VarType.BOOL
    if val.startswith("->"):
        return VarType.STRING  # divert target — not numeric
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
    return VarType.INT  # default: treat as int (could be a constant reference)
