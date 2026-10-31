from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from sqlglot import exp

type StrParamName = str
type StrAttrName = str
type StrPythonType = str


class QueryKind(StrEnum):
    ONE = "one"  # fetchrow
    MANY = "many"  # fetch
    FETCHMANY = "fetchmany"  # fetchmany
    FETCHVAL = "fetchval"  # fetchval
    EXEC = "exec"  # exec
    EXECMANY = "execmany"  # execmany


@dataclass(frozen=True, slots=True)
class Origin:
    src: Path
    file: Path
    index: int

    def __str__(self) -> str:
        return f"{self.file} (statement {self.index + 1})"


@dataclass(frozen=True, slots=True)
class SQL:
    name: str
    origin: Origin
    kind: QueryKind
    expr: exp.Expr

    def __str__(self):
        return self.expr.sql(dialect="postgres")

    def copy(self):
        return replace(self, expr=self.expr.copy())


@dataclass(frozen=True, slots=True)
class TransformedSQL:
    source: SQL
    params: dict[str, int]

    @property
    def origin(self):
        return self.source.origin


@dataclass(frozen=True, slots=True)
class TypedSQL:
    source: SQL
    typed_params: dict[StrParamName, StrPythonType]
    typed_attrs: list[tuple[StrAttrName, StrPythonType]]

    @property
    def name(self):
        return self.source.name

    @property
    def origin(self):
        return self.source.origin
