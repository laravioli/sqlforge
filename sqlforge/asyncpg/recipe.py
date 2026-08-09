from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from asyncpg import Connection
from asyncpg.prepared_stmt import PreparedStatement
from sqlglot import exp

from sqlforge.core import Config, Info, Recipe
from sqlforge.datastruct import SQL, TransformedSQL, TypedSQL
from sqlforge.loader import load
from sqlforge.postgres import PgTypeFetcher

from .converter import PythonTypeConverter, PythonTypeRegister
from .datastruct import PreparedSql
from .utils import get_conn


@dataclass
class APGRecipe(Recipe):
    info: ClassVar[Info] = {"dialect": "postgres"}
    config: Config
    conn: Connection

    # Main

    async def pipeline(self):
        queries = self._transform(load(self.config, self.info))
        prep_queries = await self._prepare(queries)
        pg_type_register = await self._get_type_register(prep_queries)
        python_type_register = PythonTypeConverter(register=pg_type_register).convert()
        return self._convert(prep_queries, python_type_register)

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
            PreparedSql(
                **sql.to_dict(), params=sql.params, prepared=await self.conn.prepare(str(sql))
            )
            for sql in sqls
        ]

    def _convert(self, sqls: list[PreparedSql], reg: PythonTypeRegister) -> list[TypedSQL]:
        return [_convert_one(sql, reg) for sql in sqls]

    # Utils

    async def _get_type_register(self, stmts: list[PreparedSql]):
        stmt_oids = get_stmt_oids(stmt.prepared for stmt in stmts)
        fetcher = PgTypeFetcher(self.conn)
        user_type_oids = await fetcher.get_user_oids()
        oids = stmt_oids | set(user_type_oids)
        return await fetcher.fetch(list(oids))


# Transform


def _transform_one(sql: SQL) -> TransformedSQL:
    params: dict[str, int] = {}
    param_nb = 1
    placeholders = sql.expr.find_all(exp.Placeholder)

    for p in placeholders:
        if p.name not in params:
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
        **sql.to_dict(),
        params=params,
    )


# Prepare


def get_stmt_oids(stmts: Iterable[PreparedStatement]):
    return {
        oid
        for stmt in stmts
        for oid in {param.oid for param in stmt.get_parameters()}
        | {attr.type.oid for attr in stmt.get_attributes()}
    }


# Convert


def _convert_one(sql: PreparedSql, reg: PythonTypeRegister) -> TypedSQL:
    params = sql.params
    pparams = sql.prepared.get_parameters()
    pattrs = sql.prepared.get_attributes()
    return TypedSQL(
        **sql.to_dict(),
        typed_params={p: reg[pp.oid] for p, pp in zip(params, pparams)},
        typed_attrs={attr.name: reg[attr.type.oid] for attr in pattrs},
    )
