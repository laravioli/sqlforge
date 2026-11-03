from __future__ import annotations

from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import asyncpg
from asyncpg.prepared_stmt import PreparedStatement
from sqlglot import exp

from sqlforge.codegen.asyncpg import AsyncpgCodegen
from sqlforge.codegen.structures import Output, PythonTypeRegister
from sqlforge.config import Config
from sqlforge.drivers import Driver
from sqlforge.errors import DriverError
from sqlforge.inference.engine import Engine
from sqlforge.introspection.fetch import Fetcher
from sqlforge.structures import SQL, QueryKind, TransformedSQL, TypedSQL
from sqlforge.utils import isidentifier


class AsyncPGDriver(Driver):
    def __init__(self, config: Config, conn: asyncpg.Connection):
        self.config = config
        self.conn = conn
        self.fetcher = Fetcher(conn)

    # Main

    async def pipeline(self, sqls: list[SQL]) -> list[Output]:
        queries = self._transform(sqls)
        prep_queries = await self._prepare(queries)
        pg_types = await self.fetcher.get_type_register(_get_stmt_oids(prep_queries))
        codegen = AsyncpgCodegen(pg_types)
        typed_queries = self._convert(prep_queries, codegen.ctx.python_types)

        return codegen.gen(Engine.from_register(pg_types, typed_queries).analyze())

    @classmethod
    async def run(cls, cfg: Config, sqls: list[SQL]):
        async with get_conn(cfg.dsn) as conn:
            driver = cls(cfg, conn)
            return await driver.pipeline(sqls)

    # Steps

    @staticmethod
    def _transform(sqls: list[SQL]):
        return [_transform_one(sql) for sql in sqls]

    async def _prepare(self, sqls: list[TransformedSQL]):
        stmts: list[PreparedStatement] = []
        for sql in sqls:
            try:
                stmt = await self.conn.prepare(
                    sql.text
                )  # NOTE: could use a pool for perf
            except _PREPARE_ERRORS as e:
                raise DriverError(f"{sql.origin}: {e}") from e
            if not stmt.get_attributes() and sql.kind not in _NO_ROWS:
                raise DriverError(f"{sql.origin}: returns no column, use :exec")

            stmts.append(stmt)

        declared = await self.fetcher.result_types([stmt.get_name() for stmt in stmts])
        return [
            PreparedSQL(sql, stmt, declared.get(stmt.get_name()) or _reported(stmt))
            for sql, stmt in zip(sqls, stmts)
        ]

    def _convert(
        self, sqls: list[PreparedSQL], reg: PythonTypeRegister
    ) -> list[TypedSQL]:
        return [_convert_one(sql, reg) for sql in sqls]


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


# Prepare
_PREPARE_ERRORS = (
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
)
_NO_ROWS = (QueryKind.EXEC, QueryKind.EXECMANY)


@dataclass(frozen=True)
class PreparedSQL:
    source: TransformedSQL
    prepared: PreparedStatement
    result_oids: list[int]  # declared types: a domain column keeps its domain


def _reported(stmt: PreparedStatement) -> list[int]:
    return [attr.type.oid for attr in stmt.get_attributes()]  # domains as base types


def _get_stmt_oids(stmts: Iterable[PreparedSQL]):
    """Helper to get postgres type oids used in sql stamements"""
    return {
        oid
        for stmt in stmts
        for oid in {param.oid for param in stmt.prepared.get_parameters()}
        | set(stmt.result_oids)
    }


# Convert


def _convert_one(sql: PreparedSQL, reg: PythonTypeRegister) -> TypedSQL:
    params = sql.source.params
    pparams = sql.prepared.get_parameters()
    pattrs = sql.prepared.get_attributes()
    return TypedSQL(
        source=sql.source,
        typed_params={p: reg[pp.oid].qualified_hint for p, pp in zip(params, pparams)},
        typed_attrs=[
            (attr.name, reg[oid].qualified_hint)
            for attr, oid in zip(pattrs, sql.result_oids, strict=True)
        ],
    )


# Connection


@asynccontextmanager
async def get_conn(dsn: str | None):
    try:
        conn = await asyncpg.connect(dsn=dsn, server_settings={"jit": "off"})
    except (OSError, asyncpg.PostgresError) as e:
        hint = (
            ""
            if dsn
            else " (no dsn configured; used PG* environment variables and defaults)"
        )
        raise ConnectionError(f"could not connect to PostgreSQL: {e}{hint}") from e
    try:
        yield cast(asyncpg.Connection, conn)
    finally:
        await conn.close()
