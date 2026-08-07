from dataclasses import dataclass
from typing import Any, ClassVar, cast

from asyncpg import Connection
from asyncpg.prepared_stmt import PreparedStatement
from asyncpg.types import Type
from sqlglot import exp

from sqlforge.core import Config, Info, Recipe
from sqlforge.datastruct import SQL, TransformedSQL, TypedSQL
from sqlforge.loader import load
from sqlforge.postgres import PgForge

from .utils import BUILTIN_SCALAR, BUILTIN_SCHEMA, TypeKind, array_boxed_type, get_conn


@dataclass
class APGRecipe(Recipe):
    info: ClassVar[Info] = {"dialect": "postgres"}
    config: Config
    conn: Connection
    pg: PgForge

    async def pipeline(self):
        queries = self._transform(load(self.config, self.info))
        _typed_queries = await self._introspect_queries(queries)
        return await self.pg.generate_type_files()

    @classmethod
    async def run(cls, cfg: Config):
        async with get_conn(cfg.dsn) as conn:
            recipe = cls(cfg, conn, PgForge(conn))
            return await recipe.pipeline()

    def _transform(self, sqls: list[SQL]):
        return [_transform_one(sql) for sql in sqls]

    async def _introspect_queries(self, sqls: list[TransformedSQL]) -> list[TypedSQL]:
        return [await self._introspect_query(sql) for sql in sqls]

    async def _introspect_query(self, sql: TransformedSQL) -> TypedSQL:
        prepared = await self.conn.prepare(str(sql))
        typed_params = _resolve_param_types(sql, prepared)
        return TypedSQL(**sql.to_dict(), typed_params=typed_params)


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


def _resolve_param_types(sql: TransformedSQL, prepared: PreparedStatement):
    typed_params: dict[str, Any] = {}
    params = sql.params
    prepared_params = prepared.get_parameters()

    for p, ps in zip(params, prepared_params):
        if ps.schema == BUILTIN_SCHEMA:
            typed_params[p] = _resolve_builtin_param_type(ps)
        else:
            typed_params[p] = _resolve_user_param_type(p, ps)

    return typed_params


def _resolve_builtin_param_type(asyncpg_type: Type) -> Any:
    kind: TypeKind = cast(TypeKind, asyncpg_type.kind)
    match kind:
        case "scalar":
            param_type = BUILTIN_SCALAR.get(asyncpg_type.name, Any)
        case "array":
            param_type = list[array_boxed_type(asyncpg_type.name)]
        case "range":
            param_type = tuple
        case "multirange":
            param_type = list[tuple]
        case _:
            param_type = Any

    return param_type


def _resolve_user_param_type(param: str, asyncpg_type: Type):
    return Any
