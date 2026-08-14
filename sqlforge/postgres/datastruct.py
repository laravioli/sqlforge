from __future__ import annotations

from enum import StrEnum
from typing import Literal, TypedDict

from msgspec import Struct, convert

type Oid = int
type PGTypeRegister = dict[Oid, PGType]
type PythonTypeRegister = dict[Oid, str]


class TypeRecord(TypedDict):
    oid: int
    ns: str
    name: str
    kind: bytes
    basetype: int | None
    basetype_name: str | None
    elemtype: int
    elemtype_name: str
    range_subtype: int | None
    range_subtype_name: str | None
    attrtypoids: list[int] | None
    attributes: str | None
    depth: int


class EnumRecord(TypedDict):
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


class PGAttribute(Struct):
    attr_type: Oid
    name: str
    position: int
    not_null: bool


class PGColumnResult(Struct):
    pass


class PGType(Struct):
    oid: Oid
    ns: str
    name: str
    kind: TypeKind

    elemtype: Literal[0] | Oid

    @property
    def is_user_defined(self):
        return self.ns not in ["pg_catalog", "information_schema"]

    @classmethod
    def convert(cls, rec: TypeRecord, **kwargs):
        return convert(dict(rec) | kwargs, cls)


class BaseType(PGType):
    pass


class RangeType(PGType):
    range_subtype: int


class CompositeType(PGType):
    attributes: list[PGAttribute]


class DomainType(PGType):
    basetype: Oid  # reference to the underlying type


class EnumType(PGType):
    values: list[str]
