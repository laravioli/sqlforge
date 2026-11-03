from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

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

    def transform(self, t: Callable[[Self], tuple[exp.Expr, dict[str, int]]]):
        expr, params = t(self)
        return TransformedSQL(
            self.name,
            self.origin,
            self.kind,
            expr,
            params,
            expr.sql(dialect="postgres", pretty=True, copy=False),
        )


@dataclass(frozen=True, slots=True)
class TransformedSQL(SQL):
    params: dict[str, int]
    text: str


@dataclass(frozen=True, slots=True)
class TypedSQL:
    source: TransformedSQL
    typed_params: dict[StrParamName, StrPythonType]
    typed_attrs: list[tuple[StrAttrName, StrPythonType]]

    @property
    def name(self):
        return self.source.name

    @property
    def origin(self):
        return self.source.origin
