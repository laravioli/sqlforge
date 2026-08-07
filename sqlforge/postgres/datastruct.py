from enum import Enum
from typing import Literal, TypedDict

from msgspec import Struct

type Oid = int


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


class TypeKind(Enum):
    BASE = b"b"
    COMPOSITE = b"c"
    DOMAIN = b"d"
    ENUM = b"e"
    PSEUDO_TYPE = b"p"
    RANGE = b"r"
    MULTI_RANGE = b"m"


class PG_Attribute(Struct):
    attr_type: Oid  # should be extracted with zip -> attrtypoids
    name: str
    position: int
    not_null: bool


class PG_Type(Struct):
    oid: Oid
    ns: str
    name: str
    kind: bytes  # TypeKind when msgspec fixed

    elemtype: Literal[0] | Oid
    elemtype_name: Literal["-"] | str


class BaseType(PG_Type):
    pass


class CompositeType(PG_Type):
    # attrtypoids: list[Oid]
    attributes: list[PG_Attribute]  # should be decoded first


class DomainType(PG_Type):
    basetype: Oid
    basetype_name: str


class EnumType(PG_Type):
    values: list[str]


class RangeType(PG_Type):
    range_subtype: Oid
    range_subtype_name: str
