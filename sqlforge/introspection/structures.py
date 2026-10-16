from __future__ import annotations

from enum import StrEnum
from typing import TypedDict

from msgspec import Struct, convert

type Oid = int
type PGTypeRegister = dict[Oid, PGType]


class TypeRecord(TypedDict):
    oid: int
    ns: str
    name: str
    kind: bytes
    comp_kind: bytes | None
    query: str | None
    basetype: int | None
    basetype_name: str | None
    elemtype: int
    elemtype_name: str
    category: str
    range_subtype: int | None
    range_subtype_name: str | None
    attrtypoids: list[int] | None
    attributes: str | None
    depth: int


class EnumRecord(TypedDict):
    oid: int
    schema_name: str
    type_name: str
    values: list[str]


class TypeKind(StrEnum):
    BASE = "b"
    COMPOSITE = "c"
    DOMAIN = "d"
    ENUM = "e"
    PSEUDO_TYPE = "p"
    RANGE = "r"
    MULTI_RANGE = "m"


class CompositeKind(StrEnum):
    TABLE = "r"
    INDEX = "i"
    SEQUENCE = "S"
    TOAST = "t"
    VIEW = "v"
    MATERIALIZED_VIEW = "m"
    TYPE = "c"
    FOREIGN_TABLE = "f"
    PARTITIONED_TABLE = "p"
    PARTITIONED_INDEX = "I"


class PGAttribute(Struct):
    attr_type: Oid
    name: str
    position: int
    nullable: bool


class PGColumnResult(Struct):
    pass


class PGType(Struct):
    oid: Oid
    ns: str
    name: str
    kind: TypeKind

    @property
    def is_user_defined(self):
        return self.ns not in ["pg_catalog", "information_schema"]

    @classmethod
    def convert(cls, rec: TypeRecord, **kwargs):
        # smart constructor
        return convert(dict(rec) | kwargs, cls)


class BaseType(PGType):
    pass


class ArrayType(PGType):
    elemtype: Oid  # element type (pg_type.typelem)


class RangeType(PGType):
    range_subtype: int


class CompositeType(PGType):
    comp_kind: CompositeKind
    attributes: list[PGAttribute]


class ViewType(CompositeType):
    query: str


class DomainType(PGType):
    # TODO: add pg_type.typnotnull
    basetype: Oid  # reference to the underlying type


class EnumType(PGType):
    values: list[str]
