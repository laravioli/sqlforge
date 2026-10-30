from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from sqlforge.stmt import SQL, AttrName, ParamName, PythonType

from .lattice import Nullability


@dataclass(frozen=True)
class ColumnResult:
    name: str
    type: str
    nullability: Nullability

    @property
    def python(self) -> str:
        return self.nullability.python(self.type)


@dataclass(frozen=True)
class Analysis:
    columns: tuple[ColumnResult, ...]
    bypassed: bool
    error: str | None = None
    internal: bool = False


@dataclass
class AnalyzedSQL:
    source: SQL
    typed_params: dict[ParamName, PythonType]
    analysis: Analysis

    @property
    def name(self):
        return self.source.name

    @property
    def origin(self):
        return self.source.origin

    @cached_property
    def typed_attrs(self) -> list[tuple[AttrName, PythonType]]:
        return [(c.name, c.python) for c in self.analysis.columns]
