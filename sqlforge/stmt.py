from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, StrEnum, auto

from sqlglot import Expr

type ParamName = str
type AttrName = str
type PythonType = str


class ParamStyle(Enum):
    QMARK = auto()
    NUMERIC = auto()
    NAMED = auto()
    FORMAT = auto()
    PY_FORMAT = auto()
    DOLLAR = auto()


class QueryKind(StrEnum):
    ONE = "one"  # fetchrow
    MANY = "many"  # fetch
    FETCHMANY = "fetchmany"  # fetchmany
    FETCHVAL = "fetchval"  # fetchval
    EXEC = "exec"  # exec
    EXECMANY = "execmany"  # execmany


@dataclass(frozen=True)
class SQL:
    name: str
    kind: QueryKind
    expr: Expr

    def __str__(self):
        return self.expr.sql(dialect="postgres")

    def copy(self):
        return replace(self, expr=self.expr.copy())


@dataclass(frozen=True)
class TransformedSQL:
    source: SQL
    params: dict[str, int]


@dataclass(frozen=True)
class TypedSQL:
    source: SQL
    typed_params: dict[ParamName, PythonType]
    typed_attrs: list[tuple[AttrName, PythonType]]

    @property
    def name(self):
        return self.source.name
