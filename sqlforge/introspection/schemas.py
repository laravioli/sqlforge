from __future__ import annotations

from collections.abc import Iterator

from sqlglot.expressions.datatypes import DataType
from sqlglot.schema import MappingSchema

from .structures import *


def relations(register: PGTypeRegister) -> Iterator[CompositeType]:
    return (t for t in register.values() if isinstance(t, CompositeType))


def mapping_schema(register: PGTypeRegister) -> MappingSchema:

    def column(attr: PGAttribute) -> DataType:
        dt = sqlglot_type(attr.attr_type, register)
        dt.set("nullable", attr.nullable)
        return dt

    return MappingSchema(
        {rel.name: {a.name: column(a) for a in rel.attributes} for rel in relations(register)},
        dialect="postgres",
    )


def sqlglot_type(oid: Oid, register: PGTypeRegister) -> DataType:
    match register[oid]:
        case DomainType(basetype=base):
            return sqlglot_type(base, register)
        case ArrayType(elemtype=elem):
            return DataType(
                this=DataType.Type.ARRAY, expressions=[sqlglot_type(elem, register)], nested=True
            )
        case t:
            return DataType.build(t.name, dialect="postgres", udt=True)
