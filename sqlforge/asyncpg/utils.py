import datetime
import decimal
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

import asyncpg

# Connection


@asynccontextmanager
async def get_conn(dsn: str):
    conn = await asyncpg.connect(dsn=dsn)
    try:
        yield cast(asyncpg.Connection, conn)
    finally:
        await conn.close()


# Types

type TypeKind = Literal[
    "scalar", "array", "composite", "range", "multirange"
]  # asyncpg classify pg types like this


# builtin
BUILTIN_SCHEMA = "pg_catalog"
BUILTIN_SCALAR: dict[str, type] = {
    "uuid": uuid.UUID,
    "bool": bool,
    "char": str,
    "bpchar": str,
    "name": str,
    "varchar": str,
    "varbit": bytes,
    "text": str,
    "xml": str,
    "bit": bytes,
    "bytea": bytes,
    "date": datetime.date,
    "time": datetime.time,
    "timetz": datetime.time,
    "timestamp": datetime.datetime,
    "timestamptz": datetime.datetime,
    "interval": datetime.timedelta,
    "float4": float,
    "float8": float,
    "int2": int,
    "int4": int,
    "int8": int,
    "numeric": decimal.Decimal,
    "json": dict[str, Any],
    "jsonb": dict[str, Any],
    "macaddr": str,
    "macaddr8": str,
    "oid": int,
    "xid": int,
    "xid8": int,
    "cid": int,
    "money": decimal.Decimal,
}


def array_boxed_type(name: str):
    scalar_type = BUILTIN_SCALAR.get(name[:-2])
    return scalar_type or Any
