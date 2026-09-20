from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from asyncpg import Connection
from asyncpg.prepared_stmt import PreparedStatement
from sqlglot import exp

from sqlforge.core.loader import load
from sqlforge.core.structures import (
    SQL,
    Config,
    Info,
    PreparedSQL,
    Recipe,
    TransformedSQL,
    TypedSQL,
)
from sqlforge.inference import Engine
from sqlforge.introspection import PgFetcher, PgSchemaGenerator

from .converter import PythonTypeConverter, PythonTypeRegister
from .generator import APGFnGenerator
from .utils import get_conn, isidentifier


@dataclass
class AsyncPGRecipe(Recipe):
    info: ClassVar[Info] = {"dialect": "postgres"}
    config: Config
    conn: Connection

    # Main

    async def pipeline(self):
        inputs = load(self.config, self.info)
        queries = self._transform(inputs)
        prep_queries = await self._prepare(queries)
        pg_type_register = await self._get_type_register(prep_queries)
        python_type_register = PythonTypeConverter(register=pg_type_register).convert()
        typed = self._convert(prep_queries, python_type_register)
        # return APGFnGenerator(sqls=typed).generate()
        return (
            inputs,
            pg_type_register,
            python_type_register,
        )

    @classmethod
    async def run(cls, cfg: Config):
        async with get_conn(cfg.dsn) as conn:
            recipe = cls(cfg, conn)
            return await recipe.pipeline()

    # Steps

    @staticmethod
    def _transform(sqls: list[SQL]):
        return [_transform_one(sql) for sql in sqls]

    async def _prepare(self, sqls: list[TransformedSQL]):
        return [
            PreparedSQL(source=sql, prepared=await self.conn.prepare(str(sql.source)))
            for sql in sqls
        ]

    def _convert(self, sqls: list[PreparedSQL], reg: PythonTypeRegister) -> list[TypedSQL]:
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


def _transform_one(sql: SQL) -> TransformedSQL:
    params: dict[str, int] = {}
    param_nb = 1
    placeholders = sql.expr.find_all(exp.Placeholder)

    for p in placeholders:
        if p.name not in params:
            assert isidentifier(p.name)
            params[p.name] = param_nb
            param_nb += 1
        p.replace(
            exp.Parameter(
                this=exp.Literal(
                    this=str(params[p.name]),
                    is_string=False,
                )
            )
        )
    return TransformedSQL(
        source=sql,
        params=params,
    )


# Prepare


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
        source=sql.source.source,
        typed_params={p: reg[pp.oid] for p, pp in zip(params, pparams)},
        typed_attrs={attr.name: reg[attr.type.oid] for attr in pattrs},
    )


# Infer Null
