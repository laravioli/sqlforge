import datetime
import decimal
import ipaddress
from functools import singledispatchmethod
from types import UnionType
from typing import get_args
from uuid import UUID

import asyncpg

from sqlforge.generator.utils import camel_case
from sqlforge.introspection import TypeConverter
from sqlforge.introspection.structures import *

from .utils import isidentifier


def type_name(t) -> str:
    match t:
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
        "char": str,
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
        "json": dict,
        "jsonb": dict,
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


class PythonTypeConverter(TypeConverter):
    @singledispatchmethod
    def _convert(self, t: PGType) -> str:
        raise NotImplementedError()

    @_convert.register
    def _(self, t: BaseType):
        if t.name in PG_BASE_TYPE:
            return PG_BASE_TYPE[t.name]
        elif t.elemtype > 0:
            elem = self.register[t.elemtype]
            return f"list[{self._convert(elem)}]"
        else:
            return "Any"

    @_convert.register
    def _(self, t: RangeType):

        pg_sub_type = self.register[t.range_subtype]
        assert not isinstance(pg_sub_type, RangeType)  # avoid infinite recursion
        python_sub_type = self._convert(pg_sub_type)
        base = f"asyncpg.Range[{python_sub_type}]"

        if t.kind is TypeKind.RANGE:
            return base
        elif t.kind is TypeKind.MULTI_RANGE:
            return f"list[{base}]"
        else:
            return "Any"

    @_convert.register
    def _(self, t: CompositeType):
        assert isidentifier(t.name)
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"

    @_convert.register
    def _(self, t: DomainType):
        assert isidentifier(t.name)
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"

    @_convert.register
    def _(self, t: EnumType):
        assert isidentifier(t.name)
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"
