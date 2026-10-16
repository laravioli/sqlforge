from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import ClassVar

from sqlglot.expressions.datatypes import DataType
from sqlglot.schema import MappingSchema

from .structures import *

type Column = PGAttribute


@dataclass(frozen=True)
class Table:
    enforced: ClassVar[bool] = True

    ns: str
    name: str
    columns: dict[str, Column]

    def maybe_null(self, col: str):
        return not self.enforced or self.columns[col].nullable

    @property
    def names(self) -> list[str]:
        return [c for c in self.columns]


class ForeignTable(Table):
    enforced: ClassVar[bool] = False


@dataclass(frozen=True)
class View:
    ns: str
    name: str
    columns: dict[str, Column]
    query: str


def composite_types(register: PGTypeRegister):
    return (t for t in register.values() if isinstance(t, CompositeType))


def sources(register: PGTypeRegister) -> Generator[Table | View]:
    for t in composite_types(register):
        columns = {c.name: c for c in t.attributes}
        match t:
            case CompositeType(comp_kind=CompositeKind.TABLE | CompositeKind.PARTITIONED_TABLE):
                yield Table(t.ns, t.name, columns)

            case CompositeType(comp_kind=CompositeKind.FOREIGN_TABLE):
                yield ForeignTable(t.ns, t.name, columns)

            case ViewType():
                yield View(t.ns, t.name, columns, t.query)


def mapping_schema(register: PGTypeRegister) -> MappingSchema:

    def column(attr: Column) -> DataType:
        dt = _sqlglot_type(attr.attr_type, register)
        dt.set("nullable", attr.nullable)
        return dt

    return MappingSchema(
        {rel.name: {k: column(v) for k, v in rel.columns.items()} for rel in sources(register)},
        dialect="postgres",
    )


def _sqlglot_type(oid: Oid, register: PGTypeRegister) -> DataType:
    match register[oid]:
        case DomainType(basetype=base):
            return _sqlglot_type(base, register)
        case ArrayType(elemtype=elem):
            return DataType(
                this=DataType.Type.ARRAY, expressions=[_sqlglot_type(elem, register)], nested=True
            )
        case t:
            return DataType.build(t.name, dialect="postgres", udt=True)
