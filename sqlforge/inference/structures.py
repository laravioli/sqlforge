from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from sqlforge.introspection.structures import Oid, PreparedSQL

from .lattice import Nullability


@dataclass(frozen=True, slots=True)
class Composite:
    fields: tuple[tuple[str, Shape], ...]
    stored: Oid | None = None


@dataclass(frozen=True, slots=True)
class Array:
    elem: Shape


type Shape = Composite | Array | Literal["scalar", "unknown"]


@dataclass(frozen=True, slots=True)
class ColumnResult:
    nullability: Nullability
    stored: Oid | None = None


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
