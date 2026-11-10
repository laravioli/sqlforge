from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from sqlforge.codegen.asyncpg import Codegen
from sqlforge.errors import DriverError
from sqlforge.utils import isidentifier

if TYPE_CHECKING:
    from sqlforge.config import Config
    from sqlforge.inference.structures import AnalyzedSQL
    from sqlforge.introspection.structures import PGTypeRegister
    from sqlforge.structures import SQL, TransformedSQL


class Asyncpg:
    def __init__(self, cfg: Config):
        self.config = cfg

    @staticmethod
    def transform(sql: SQL) -> TransformedSQL:
        return sql.transform(_t)

    def out(self, pg_types: PGTypeRegister, sqls: list[AnalyzedSQL]):
        return Codegen(pg_types, self.config.format).gen(sqls)


_RESERVED_PARAMS = frozenset({"conn", "timeout", "record_class", "column", "args"})


def _t(sql: SQL):
    """compute params and modify sql expression in place (no copy)"""
    params: dict[str, int] = {}
    # list(): the walk must not reach the $N nodes inserted below
    for p in list(sql.expr.find_all(exp.Parameter, exp.Placeholder)):
        if isinstance(p, exp.Parameter):
            raise DriverError(f"{sql.origin}: use :name parameters, not ${p.name}")
        if not isidentifier(p.name) or p.name in _RESERVED_PARAMS:
            raise DriverError(f"{sql.origin}: {p.name!r} can't be a parameter name")

        n = params.setdefault(p.name, len(params) + 1)
        p.replace(exp.Parameter(this=exp.Literal.number(n)))
    return sql.expr, params
