import datetime
import decimal
import ipaddress
from dataclasses import dataclass
from functools import singledispatchmethod
from types import UnionType
from uuid import UUID

import asyncpg

from sqlforge.generator.utils import camel_case
from sqlforge.postgres.datastruct import *


def type_name(t):
    match t:
        case type():
            return getattr(t, "__name__", str(t))
        case UnionType():
            return t.__str__()
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


@dataclass(frozen=True)
class PythonTypeConverter:
    register: PGTypeRegister

    def convert(self) -> PythonTypeRegister:
        return {k: self._to_python(v) for k, v in self.register.items()}

    @singledispatchmethod
    def _to_python(self, t: PGType) -> str:
        raise NotImplementedError()

    @_to_python.register
    def _(self, t: BaseType):
        if t.name in PG_BASE_TYPE:
            return PG_BASE_TYPE[t.name]
        elif t.name[0] == "_" and t.elemtype > 0:  # elemtype always > 0
            elem = self.register[t.elemtype]
            return f"list[{self._to_python(elem)}]"
        else:  # other postgres type like int2vector
            return "Any"

    @_to_python.register
    def _(self, t: RangeType):

        pg_sub_type = self.register[t.range_subtype]
        assert not isinstance(pg_sub_type, RangeType)  # avoid infinite recursion
        python_sub_type = self._to_python(pg_sub_type)
        base = f"tuple[{python_sub_type},{python_sub_type}]"

        if t.kind is TypeKind.RANGE:
            return base
        elif t.kind is TypeKind.MULTI_RANGE:
            return f"list[{base}]"
        else:
            return "Any"

    @_to_python.register
    def _(self, t: CompositeType):
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"

    @_to_python.register
    def _(self, t: DomainType):
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"

    @_to_python.register
    def _(self, t: EnumType):
        if t.is_user_defined:
            return camel_case(t.name)
        else:
            return "Any"
