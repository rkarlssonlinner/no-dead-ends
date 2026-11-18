from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


# ---------------------------------------------------------------------------
# Symbolic expressions — intermediate representation between parser and Z3
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntLit:
    value: int

@dataclass(frozen=True)
class BoolLit:
    value: bool

@dataclass(frozen=True)
class StringLit:
    value: str

@dataclass(frozen=True)
class VarRef:
    name: str

@dataclass(frozen=True)
class VisitCount:
    target: str

@dataclass(frozen=True)
class BinOp:
    op: str
    left: SymExpr
    right: SymExpr

@dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: SymExpr

SymExpr = Union[IntLit, BoolLit, StringLit, VarRef, VisitCount, BinOp, UnaryOp]


# ---------------------------------------------------------------------------
# Variable declarations
# ---------------------------------------------------------------------------

class VarType(Enum):
    INT = "int"
    BOOL = "bool"
    STRING = "string"

@dataclass(frozen=True)
class VarDecl:
    name: str
    var_type: VarType
    initial_value: int | bool | str


# ---------------------------------------------------------------------------
# Story graph nodes and edges
# ---------------------------------------------------------------------------

class NodeKind(Enum):
    ENTRY = "entry"
    KNOT = "knot"
    STITCH = "stitch"
    GATHER = "gather"
    TERMINAL = "terminal"

@dataclass
class StoryNode:
    id: str
    kind: NodeKind
    text: str = ""
    tags: list[str] = field(default_factory=list)

@dataclass
class StoryEdge:
    source: str
    target: str
    edge_id: str = ""
    guard: SymExpr | None = None
    mutations: list[tuple[str, SymExpr]] = field(default_factory=list)
    once_only: bool = False
    is_fallback: bool = False
    choice_text: str = ""


# ---------------------------------------------------------------------------
# Story graph — the contract between parser and encoder
# ---------------------------------------------------------------------------

@dataclass
class StoryGraph:
    nodes: dict[str, StoryNode]
    edges: list[StoryEdge]
    variables: dict[str, VarDecl]
    entry_node: str

    _outgoing: dict[str, list[StoryEdge]] = field(default_factory=dict, repr=False)
    _incoming: dict[str, list[StoryEdge]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._build_indices()

    def _build_indices(self) -> None:
        self._outgoing = {nid: [] for nid in self.nodes}
        self._incoming = {nid: [] for nid in self.nodes}
        for i, e in enumerate(self.edges):
            if not e.edge_id:
                e.edge_id = f"e_{i}"
            if e.source in self._outgoing:
                self._outgoing[e.source].append(e)
            if e.target in self._incoming:
                self._incoming[e.target].append(e)

    def outgoing(self, node_id: str) -> list[StoryEdge]:
        return self._outgoing.get(node_id, [])

    def incoming(self, node_id: str) -> list[StoryEdge]:
        return self._incoming.get(node_id, [])

    def terminals(self) -> list[str]:
        return [nid for nid, n in self.nodes.items() if n.kind == NodeKind.TERMINAL]

    def non_terminals(self) -> list[str]:
        return [nid for nid, n in self.nodes.items() if n.kind != NodeKind.TERMINAL]

    def validate(self) -> list[str]:
        warnings = []
        if self.entry_node not in self.nodes:
            warnings.append(f"Entry node '{self.entry_node}' not in nodes")
        for e in self.edges:
            if e.source not in self.nodes:
                warnings.append(f"Edge {e.edge_id}: source '{e.source}' not in nodes")
            if e.target not in self.nodes:
                warnings.append(f"Edge {e.edge_id}: target '{e.target}' not in nodes")
        return warnings
