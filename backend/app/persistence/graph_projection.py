"""Rebuildable graph projection contract.

The relational evidence store is authoritative. A Neo4j deployment or another
graph engine may implement this interface and can be rebuilt from immutable
normalized transactions and graph snapshots at any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    projection_name: str
    source_revision: int
    source_digest: str
    nodes_written: int
    edges_written: int


class GraphProjection(Protocol):
    def rebuild(self, *, projection_name: str, through_revision: int) -> ProjectionResult: ...

    def delete_projection(self, *, projection_name: str) -> None: ...
