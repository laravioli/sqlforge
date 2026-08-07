import datetime
import decimal
from typing import Any
from uuid import UUID


def type_name(t):
    return getattr(t, "__name__", str(t))


PG_CATALOG = "pg_catalog"
PG_BASE_TYPE: dict[str, str] = {
    k: type_name(v)
    for k, v in {
        "uuid": UUID,
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
    }.items()
}
