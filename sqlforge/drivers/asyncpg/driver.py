from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from asyncpg import Connection, PostgresError
from asyncpg.prepared_stmt import PreparedStatement
from sqlglot import exp

from sqlforge.codegen.output import make_files, make_schemas
from sqlforge.codegen.structures import Output
from sqlforge.config import Config
from sqlforge.drivers import Driver
from sqlforge.errors import DriverError
from sqlforge.inference.engine import Engine
from sqlforge.introspection.codegen import PgSchemaCodegen, get_user_schema_names
from sqlforge.introspection.fetch import PgFetcher
from sqlforge.structures import (
    SQL,
    TransformedSQL,
    TypedSQL,
)

from .codegen import generate
from .converter import PythonTypeRegister, python_types
from .utils import get_conn, isidentifier


@dataclass
class AsyncPGDriver(Driver):
    config: Config
    conn: Connection

    # Main

    async def pipeline(self, sqls: list[SQL]) -> list[Output]:
        queries = self._transform(sqls)
        prep_queries = await self._prepare(queries)
        pg_type_register = await self._get_type_register(prep_queries)
        python_type_register = python_types(register=pg_type_register)
        typed_queries = self._convert(prep_queries, python_type_register)
        final = Engine.from_register(pg_type_register, typed_queries).analyze()
        nss = get_user_schema_names(pg_type_register)

        return [
            *make_schemas(
                nss,
                PgSchemaCodegen(pg_type_register, python_type_register).generate_schema,
            ),
            *make_files(final, nss, generate),
        ]

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
        prepared: list[PreparedSQL] = []
        for sql in sqls:
            try:
                stmt = await self.conn.prepare(
                    sql.text
                )  # NOTE: could use a pool for perf
            except PostgresError as e:
                raise DriverError(f"{sql.origin}: {e}") from e
            prepared.append(PreparedSQL(source=sql, prepared=stmt))
        return prepared

    def _convert(
        self, sqls: list[PreparedSQL], reg: PythonTypeRegister
    ) -> list[TypedSQL]:
        return [_convert_one(sql, reg) for sql in sqls]

    # Utils

    async def _get_type_register(self, stmts: list[PreparedSQL]):
        stmt_oids = get_stmt_oids(stmt.prepared for stmt in stmts)
        fetcher = PgFetcher(self.conn)
        user_type_oids = await fetcher.get_user_oids()
        oids = stmt_oids | set(
            user_type_oids
        )  # we combine stamement oids with introspected db oids
        return await fetcher.fetch_types(list(oids))


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


@dataclass(frozen=True)
class PreparedSQL:
    source: TransformedSQL
    prepared: PreparedStatement


def get_stmt_oids(stmts: Iterable[PreparedStatement]):
    """Helper to get postgres type oids used in sql stamements"""
    return {
        oid
        for stmt in stmts
        for oid in {param.oid for param in stmt.get_parameters()}
        | {attr.type.oid for attr in stmt.get_attributes()}
    }


# Convert


def _convert_one(sql: PreparedSQL, reg: PythonTypeRegister) -> TypedSQL:
    params = sql.source.params
    pparams = sql.prepared.get_parameters()
    pattrs = sql.prepared.get_attributes()
    return TypedSQL(
        source=sql.source,
        typed_params={p: reg[pp.oid].qualified_hint for p, pp in zip(params, pparams)},
        typed_attrs=[(attr.name, reg[attr.type.oid].qualified_hint) for attr in pattrs],
    )


# Infer Null
