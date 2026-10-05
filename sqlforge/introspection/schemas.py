from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.expressions.datatypes import DataType
from sqlglot.schema import MappingSchema

from .structures import *


def relations(register: PGTypeRegister) -> Iterator[CompositeType]:
    return (t for t in register.values() if isinstance(t, CompositeType))


@dataclass(frozen=True)
class Column:
    position: int
    nullable: bool


@dataclass(frozen=True)
class Table:
    columns: dict[str, Column]
    checks: tuple[exp.Expr, ...] = ()
    keys: tuple[tuple, ...] = ()

    def column(self, name: str):
        return self.columns[name]

    @property
    def names(self) -> list[str]:
        return [c for c in self.columns]


def user_tables(register: PGTypeRegister) -> Mapping[str, Table]:
    def column(attr: PGAttribute):
        return Column(position=attr.position, nullable=attr.nullable)

    return {
        rel.name: Table(columns={a.name: column(a) for a in rel.attributes})
        for rel in relations(register)
    }


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
