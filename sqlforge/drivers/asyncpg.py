from __future__ import annotations

from sqlglot import exp

from sqlforge.codegen.asyncpg import AsyncpgCodegen
from sqlforge.codegen.structures import Output
from sqlforge.config import Config
from sqlforge.drivers import Driver
from sqlforge.errors import DriverError
from sqlforge.inference.engine import Engine
from sqlforge.introspection.fetch import Fetcher
from sqlforge.structures import SQL, TransformedSQL
from sqlforge.utils import isidentifier


class AsyncPGDriver(Driver):
    def __init__(self, config: Config):
        self.config = config

    async def pipeline(self, sqls: list[SQL]) -> list[Output]:
        transformed = self._transform(sqls)
        pg_types, prepared = await Fetcher.fetch(self.config.dsn, transformed)
        analyzed = Engine(pg_types).analyze(prepared)
        return AsyncpgCodegen(pg_types).gen(analyzed)

    @classmethod
    async def run(cls, cfg: Config, sqls: list[SQL]):
        driver = cls(cfg)
        return await driver.pipeline(sqls)

    @staticmethod
    def _transform(sqls: list[SQL]):
        return [_transform_one(sql) for sql in sqls]


# Transform
_RESERVED_PARAMS = frozenset({"conn", "timeout", "record_class", "column", "args"})


def _transform_one(sql: SQL) -> TransformedSQL:
    return sql.transform(_t)


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
