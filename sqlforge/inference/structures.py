from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from sqlforge.introspection.structures import PreparedSQL

from .lattice import Nullability


@dataclass(frozen=True, slots=True)
class ColumnResult:
    nullability: Nullability


@dataclass(frozen=True, slots=True)
class Analysis:
    columns: tuple[ColumnResult, ...]
    bypassed: bool
    error: str | None = None
    internal: bool = False


@dataclass
class AnalyzedSQL:
    source: PreparedSQL
    analysis: Analysis

    @cached_property
    def name(self):
        return self.source.name

    @cached_property
    def origin(self):
        return self.source.origin
