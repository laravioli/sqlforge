import asyncio
from typing import cast

from asyncpg import Connection
from msgspec import convert
from msgspec.json import Decoder

from sqlforge.generator import EnumText, StructText, Text

from .datastruct import *
from .datastruct import CompositeType, EnumType
from .stmt import LOOKUP_TYPES, TYPE_ENUM, USER_TYPE_OIDS
from .typmap import PG_BASE_TYPE

type TypeRegister = dict[Oid, PG_Type]


ATTR_DECODER = Decoder(type=list[PG_Attribute])


class PgForge:
    def __init__(self, conn: Connection):
        self._conn = conn
        self._type_register: asyncio.Task[TypeRegister] | None = None

    async def get_type_register(self):
        if self._type_register is None:

            async def _fetch():
                oids = await self._conn.fetchval(USER_TYPE_OIDS)
                records = cast(list[TypeRecord], await self._conn.fetch(LOOKUP_TYPES, oids))
                enums = {r["type_name"]: r["values"] for r in await self._conn.fetch(TYPE_ENUM)}
                return await self._convert_type_records(records, enums)

            self._type_register = asyncio.create_task(_fetch())

        return await self._type_register

    async def _convert_type_records(
        self, recs: list[TypeRecord], enums: dict[str, list[str]]
    ) -> TypeRegister:
        def _matcher(rec: TypeRecord) -> tuple[int, PG_Type]:
            kind = TypeKind(rec["kind"])
            match kind:
                case TypeKind.BASE:
                    return rec["oid"], convert(rec, BaseType)

                case TypeKind.COMPOSITE:
                    assert rec["attributes"] is not None
                    attributes = ATTR_DECODER.decode(rec["attributes"])
                    return rec["oid"], convert({**rec, "attributes": attributes}, CompositeType)

                case TypeKind.DOMAIN:
                    return rec["oid"], convert(rec, DomainType)

                case TypeKind.ENUM:
                    values = enums[rec["name"]]
                    a = rec["oid"], convert({**rec, "values": values}, EnumType)
                    return a

                case TypeKind.PSEUDO_TYPE:
                    raise NotImplementedError()

                case TypeKind.RANGE | TypeKind.MULTI_RANGE:
                    return rec["oid"], convert(rec, RangeType)

        return dict(_matcher(rec) for rec in recs)

    async def generate_type_files(self):
        text = Text("")
        register = await self.get_type_register()

        def get_pg_type(oid: int):
            t = register[oid]
            if t.kind == b"b":
                return PG_BASE_TYPE[t.name]
            return t.name.capitalize()

        def generate_class(c: CompositeType):
            class_text = StructText.class_name(c.name)
            for attr in c.attributes:
                class_text = class_text.add_attribute(attr.name, get_pg_type(attr.attr_type))
            return class_text.newline()

        def generate_enum(e: EnumType):
            enum_text = EnumText.enum(e.name)
            for v in e.values:
                enum_text = enum_text.add_value(v.upper(), v)
            return enum_text.newline()

        for pg_type in register.values():
            match pg_type:
                case CompositeType():
                    text = text.add(str(generate_class(pg_type)))
                case EnumType():
                    text = text.add(str(generate_enum(pg_type)))
                case _:
                    pass
        return text
