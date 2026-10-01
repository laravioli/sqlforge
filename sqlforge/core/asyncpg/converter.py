import datetime
import decimal
import ipaddress
from types import UnionType
from typing import get_args
from uuid import UUID

import asyncpg

from sqlforge.core.structures import PythonType
from sqlforge.generator.utils import camel_case
from sqlforge.introspection.structures import (
    ArrayType,
    BaseType,
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGTypeRegister,
    RangeType,
    TypeKind,
)

from .utils import isidentifier

type PythonTypeRegister = dict[Oid, PythonType]


def type_name(t) -> str:
    match t:
        case type() if (
            t.__module__.startswith("asyncpg") and getattr(asyncpg, t.__qualname__, None) is t
        ):
            return f"asyncpg.{t.__qualname__}"  # public name, not the internal module path

        case type():
            module = t.__module__
            name = t.__qualname__
            return name if module == "builtins" else f"{module}.{name}"

        case UnionType():
            return " | ".join(type_name(arg) for arg in get_args(t))

        case str():
            return t

        case _:
            raise TypeError(f"Unsupported type: {t!r}")


PG_BASE_TYPE: dict[str, str] = {
    k: type_name(v)
    for k, v in {
        "record": asyncpg.Record,
        "bit": asyncpg.BitString,
        "varbit": asyncpg.BitString,
        "bool": bool,
        "box": asyncpg.Box,
        "bytea": bytes,
        "char": bytes,
        "name": str,
        "varchar": str,
        "text": str,
        "xml": str,
        "bpchar": str,
        "cidr": ipaddress.IPv4Network | ipaddress.IPv6Network,
        "inet": ipaddress.IPv4Interface
        | ipaddress.IPv6Interface
        | ipaddress.IPv4Address
        | ipaddress.IPv6Address,
        "macaddr": str,
        "macaddr8": str,
        "circle": asyncpg.Circle,
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
        "json": str,  # asyncpg returns json / jsonb as str unless you register a codec
        "jsonb": str,
        "line": asyncpg.Line,
        "lseg": asyncpg.LineSegment,
        "money": str,
        "path": asyncpg.Path,
        "point": asyncpg.Point,
        "polygon": asyncpg.Polygon,
        "uuid": UUID,
        "tid": tuple,
        "oid": int,
        "xid": int,
        "xid8": int,
        "cid": int,
    }.items()
}


def python_type(oid: Oid, register: PGTypeRegister) -> PythonType:
    match register[oid]:
        case ArrayType(elemtype=elem):
            return f"list[{python_type(elem, register)} | None]"
        case RangeType(kind=kind, range_subtype=sub):
            rng = f"asyncpg.Range[{python_type(sub, register)}]"
            return f"list[{rng}]" if kind is TypeKind.MULTI_RANGE else rng

        case CompositeType() | DomainType() | EnumType() as t if t.is_user_defined:
            assert isidentifier(t.name)
            return camel_case(t.name)

        case DomainType(basetype=base):
            return python_type(base, register)

        case BaseType(name=name):
            return PG_BASE_TYPE.get(name, "Any")

        case _:  # system composite types
            return "Any"


def python_types(register: PGTypeRegister) -> PythonTypeRegister:
    return {oid: python_type(oid, register) for oid in register}
