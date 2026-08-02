from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Any, Literal

from sqlglot import Expr

type SupportedDialect = Literal["postgres"]


class QueryKind(StrEnum):
    ONE = "one"
    MANY = "many"
    EXEC = "exec"


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

    def to_dict(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "dialect": self.dialect,
            "expr": self.expr,
        }


@dataclass(frozen=True)
class TransformedSQL(SQL):
    params: dict[str, int]


@dataclass(frozen=True)
class TypedSQL(SQL):
    typed_params: dict[str, Any]
    # typed_attributes: dict[str,Any]


@dataclass(frozen=True)
class GeneratedSQL(SQL):
    fn: str
