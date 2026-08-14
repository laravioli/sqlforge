from collections.abc import Sequence
from typing import cast

from asyncpg import Connection
from msgspec.json import Decoder

from .datastruct import *
from .datastruct import PGAttribute
from .stmt import LOOKUP_TYPES, TYPE_ENUM, USER_TYPE_OIDS

ATTR_DECODER = Decoder(type=list[PGAttribute])


class PgTypeFetcher:
    def __init__(self, conn: Connection):
        self._conn = conn

    async def fetch(self, oids: Sequence[int] = ()):
        records = cast(list[TypeRecord], await self._conn.fetch(LOOKUP_TYPES, oids))
        enums = {r["type_name"]: r["values"] for r in await self._conn.fetch(TYPE_ENUM)}
        return self._convert_type_records(records, enums)

    async def get_user_oids(self):
        return cast(Sequence[Oid], await self._conn.fetchval(USER_TYPE_OIDS))

    def _convert_type_records(
        self, recs: list[TypeRecord], enums: dict[str, list[str]]
    ) -> PGTypeRegister:

        register: PGTypeRegister = {}

        for rec in recs:
            kind = TypeKind(rec["kind"].decode())
            match kind:
                case TypeKind.BASE:
                    register[rec["oid"]] = BaseType.convert(
                        rec,
                        kind=kind,
                    )

                case TypeKind.COMPOSITE:
                    assert rec["attributes"] is not None
                    attributes = ATTR_DECODER.decode(rec["attributes"])
                    register[rec["oid"]] = CompositeType.convert(
                        rec,
                        kind=kind,
                        attributes=attributes,
                    )

                case TypeKind.DOMAIN:
                    register[rec["oid"]] = DomainType.convert(
                        rec,
                        kind=kind,
                    )

                case TypeKind.ENUM:
                    values = enums[rec["name"]]

                    register[rec["oid"]] = EnumType.convert(
                        rec,
                        kind=kind,
                        values=values,
                    )

                case TypeKind.PSEUDO_TYPE:
                    raise NotImplementedError()

                case TypeKind.RANGE | TypeKind.MULTI_RANGE:
                    register[rec["oid"]] = RangeType.convert(
                        rec,
                        kind=kind,
                    )

        return register
