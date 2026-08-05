from enum import Enum
from typing import Literal

from msgspec import Struct

type Oid = int


class TypeKind(Enum):
    BASE = b"b"
    COMPOSITE = b"c"
    DOMAIN = b"d"
    ENUM = "e"
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
    kind: TypeKind

    elemtype: Literal[0] | Oid
    elemtype_name: Literal["-"] | str

    range_subtype: Oid
    range_subtype_name: str


class BaseType(PG_Type):
    pass


class CompositeType(PG_Type):
    # attrtypoids: list[Oid]
    attributes: list[PG_Attribute]  # should be decoded first


class DomainType(PG_Type):
    basetype: Oid
    basetype_name: str


class EnumType(PG_Type):
    values: list[str]  # should be populated after querying


class RangeType(PG_Type):
    range_subtype: Oid
    range_subtype_name: str


class MultiRangeType(PG_Type):
    range_subtype: Oid
    range_subtype_name: str
