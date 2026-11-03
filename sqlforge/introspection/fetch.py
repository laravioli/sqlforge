import asyncio
from collections.abc import Sequence
from typing import cast

from asyncpg import Connection
from msgspec.json import Decoder

from .stmt import LOOKUP_TYPES, RESULT_TYPES, TYPE_ENUM, USER_TYPE_OIDS
from .structures import (
    ArrayType,
    BaseType,
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGAttribute,
    PGTypeRegister,
    PseudoType,
    RangeType,
    TypeKind,
    TypeRecord,
    ViewType,
)

ATTR_DECODER = Decoder(type=list[PGAttribute])


class Fetcher:
    def __init__(self, conn: Connection):
        self._conn = conn
        self._udf_oids: asyncio.Task[Sequence[Oid] | None] | None = None

    async def get_type_register(self, stmt_oids: set[int]) -> PGTypeRegister:
        user_type_oids = await self._get_user_oids()
        oids = stmt_oids | set(user_type_oids)
        return await self._types(list(oids))

    async def _types(self, oids: Sequence[int] = ()):
        records = cast(list[TypeRecord], await self._conn.fetch(LOOKUP_TYPES, oids))
        enums = {r["oid"]: r["values"] for r in await self._conn.fetch(TYPE_ENUM)}
        return self._convert_type_records(records, enums)

    async def _get_user_oids(self) -> Sequence[Oid]:
        if self._udf_oids is None:
            self._udf_oids = asyncio.create_task(self._conn.fetchval(USER_TYPE_OIDS))
        return await self._udf_oids or ()

    async def result_types(self, names: Sequence[str]) -> dict[str, list[Oid] | None]:
        if self._conn.get_server_version() < (16,):
            return {}
        records = await self._conn.fetch(RESULT_TYPES, names)
        return {r["name"]: r["result_types"] for r in records}

    async def fetch_fn(self):
        pass

    def _convert_type_records(
        self, recs: list[TypeRecord], enums: dict[Oid, list[str]]
    ) -> PGTypeRegister:

        register: PGTypeRegister = {}

        for rec in recs:
            kind = TypeKind(rec["kind"].decode())
            match kind:
                case TypeKind.BASE:
                    # arrays are base types with typcategory 'A'; typelem alone also matches name, point
                    cls = ArrayType if rec["category"] == "A" else BaseType
                    register[rec["oid"]] = cls.convert(rec, kind=kind)

                case TypeKind.COMPOSITE:
                    assert rec["comp_kind"] is not None
                    attributes = (
                        ATTR_DECODER.decode(rec["attributes"])
                        if rec["attributes"]
                        else []
                    )
                    comp_kind = rec["comp_kind"].decode()

                    if comp_kind in ["v", "m"]:
                        register[rec["oid"]] = ViewType.convert(
                            rec,
                            kind=kind,
                            comp_kind=comp_kind,
                            query=rec["query"],
                            attributes=attributes,
                        )
                    else:
                        register[rec["oid"]] = CompositeType.convert(
                            rec,
                            kind=kind,
                            comp_kind=comp_kind,
                            attributes=attributes,
                        )

                case TypeKind.DOMAIN:
                    register[rec["oid"]] = DomainType.convert(
                        rec,
                        kind=kind,
                    )

                case TypeKind.ENUM:
                    values = enums.get(rec["oid"], [])

                    register[rec["oid"]] = EnumType.convert(
                        rec,
                        kind=kind,
                        values=values,
                    )

                case TypeKind.PSEUDO_TYPE:
                    register[rec["oid"]] = PseudoType.convert(rec, kind=kind)

                case TypeKind.RANGE | TypeKind.MULTI_RANGE:
                    register[rec["oid"]] = RangeType.convert(
                        rec,
                        kind=kind,
                    )

        return register
