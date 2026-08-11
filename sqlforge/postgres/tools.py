from collections.abc import Sequence
from typing import cast

from asyncpg import Connection
from msgspec.json import Decoder

from sqlforge.generator import DomainText, EnumText, StructText, Text

from .datastruct import *
from .stmt import LOOKUP_TYPES, TYPE_ENUM, USER_TYPE_OIDS

ATTR_DECODER = Decoder(type=list[PG_Attribute])


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


class PgSchemaGenerator:
    def __init__(
        self,
        pg_reg: PGTypeRegister,
        python_reg: PythonTypeRegister,
    ):
        self.pg_reg = pg_reg
        self.python_reg = python_reg

    def generate_schema(self) -> Text:
        txt = (
            Text()
            .import_("asyncpg")
            .import_("datetime")
            .import_("decimal")
            .import_("ipaddress")
            .import_("uuid")
            .newline()
        )

        for pg_text in self._pg_reader():
            txt.add(pg_text).newline()

        return txt

    def _pg_reader(self):
        for pg_type in self.pg_reg.values():
            match pg_type:
                case CompositeType():
                    yield self._composite(pg_type)
                case DomainType():
                    yield self._domain(pg_type)
                case EnumType():
                    yield self._enum(pg_type)

    def _composite(self, composite: CompositeType):
        txt = StructText(composite.name)
        for attr in composite.attributes:
            txt.add_attribute(attr.name, self.python_reg[attr.attr_type])
        return txt

    def _enum(self, enum: EnumType):
        txt = EnumText(enum.name)
        for value in enum.values:
            txt.add_value(value.upper(), value)
        return txt

    def _domain(self, domain: DomainType):
        return DomainText(domain.name, self.python_reg[domain.basetype])
