from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, StrEnum, auto
from typing import Literal

from asyncpg.prepared_stmt import PreparedStatement
from sqlglot import Expr


class ParamStyle(Enum):
    QMARK = auto()
    NUMERIC = auto()
    NAMED = auto()
    FORMAT = auto()
    PY_FORMAT = auto()
    DOLLAR = auto()


@dataclass(frozen=True)
class SQL:
    name: str
    kind: QueryKind
    dialect: SupportedDialect
    expr: Expr

    def __str__(self):
        return self.expr.sql(dialect=self.dialect)

    def copy(self):
        return replace(self, expr=self.expr.copy())


type SupportedDialect = Literal["postgres"]


class QueryKind(StrEnum):
    ONE = "one"  # fetchrow
    MANY = "many"  # fetch
    FETCHMANY = "fetchmany"  # fetchmany
    FETCHVAL = "fetchval"  # fetchval
    EXEC = "exec"  # exec
    EXECMANY = "execmany"  # execmany


@dataclass(frozen=True)
class TransformedSQL:
    source: SQL
    params: dict[str, int]


@dataclass(frozen=True)
class PreparedSQL:
    source: TransformedSQL
    prepared: PreparedStatement


type PythonType = str


@dataclass(frozen=True)
class TypedSQL:
    source: SQL
    typed_params: dict[ParamName, PythonType]
    typed_attrs: dict[AttrName, PythonType]


@dataclass(frozen=True)
class GeneratedSQL(SQL):
    fn: str


type ParamName = str
type AttrName = str
