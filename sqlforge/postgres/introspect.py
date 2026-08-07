from dataclasses import dataclass
from typing import cast

from asyncpg import Connection
from msgspec import convert
from msgspec.json import Decoder

from .datastruct import *
from .stmt import LOOKUP_TYPES, TYPE_ENUM, USER_TYPE_OIDS

type TypeRegister = dict[Oid, PG_Type]


ATTR_DECODER = Decoder(type=list[PG_Attribute])


@dataclass
class PGPIntro:
    type_records: list[TypeRecord]
    enums: dict[str, list[str]]
    conn: Connection

    @classmethod
    async def make(cls, conn: Connection):
        oids = await conn.fetchval(USER_TYPE_OIDS)
        type_records = cast(list[TypeRecord], await conn.fetch(LOOKUP_TYPES, oids))
        enums = {r["type_name"]: r["values"] for r in await conn.fetch(TYPE_ENUM)}
        return cls(type_records=type_records, enums=enums, conn=conn)

    def introspect(self) -> dict[int, PG_Type]:
        return {k: v for k, v in map(self.parse_one, self.type_records)}

    def parse_one(self, rec: TypeRecord) -> tuple[int, PG_Type]:

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
                values = self.enums[rec["name"]]
                a = rec["oid"], convert({**rec, "values": values}, EnumType)
                return a

            case TypeKind.PSEUDO_TYPE:
                raise NotImplementedError()

            case TypeKind.RANGE | TypeKind.MULTI_RANGE:
                return rec["oid"], convert(rec, RangeType)
