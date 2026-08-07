from typing import Any, cast

from asyncpg import Connection
from asyncpg.prepared_stmt import PreparedStatement
from asyncpg.types import Type

from sqlforge.data import TransformedSQL, TypedSQL
from sqlforge.postgres import PGPIntro

from .utils import BUILTIN_SCALAR, BUILTIN_SCHEMA, TypeKind, array_boxed_type, get_connection

# Data


async def introspect_schema(conn: Connection):

    intro = await PGPIntro.make(conn=conn)
    return intro.introspect()


# Query


async def introspect_queries(sqls: list[TransformedSQL], *, dsn: str) -> list[TypedSQL]:
    async with get_connection(dsn) as conn:
        return [await _introspect_one(sql, conn) for sql in sqls]


async def _introspect_one(sql: TransformedSQL, conn: Connection) -> TypedSQL:
    prepared = await conn.prepare(str(sql))
    typed_params = _resolve_param_types(sql, prepared)
    return TypedSQL(**sql.to_dict(), typed_params=typed_params)


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
