from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.expressions.datatypes import DataType
from sqlglot.schema import MappingSchema

from .structures import *

type Column = PGAttribute

DEFAULT_SEARCH_PATH = ("pg_catalog", "public")


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


class SearchPathSchema(MappingSchema):
    """ns -> table -> columns; an unqualified table is looked up along the search path"""

    def __init__(self, mapping: dict, search_path: Sequence[str]):
        postgres = Postgres()
        postgres.SUPPORTS_STRUCT_STAR_EXPANSION = True  # type: ignore
        super().__init__(mapping, dialect=postgres, normalize=False)
        self.search_path = tuple(search_path)

    def find(
        self, table: exp.Table, raise_on_missing: bool = True, ensure_data_types: bool = False
    ) -> Any | None:
        if not table.db:
            for ns in self.search_path:
                found = super().find(exp.table_(table.name, db=ns), False, ensure_data_types)
                if found is not None:
                    return found
        return super().find(table, raise_on_missing, ensure_data_types)


def mapping_schema(
    register: PGTypeRegister, search_path: Sequence[str] = DEFAULT_SEARCH_PATH
) -> SearchPathSchema:

    def sqlglot_type(oid: Oid, register: PGTypeRegister) -> DataType:
        match register[oid]:
            case DomainType(basetype=base):
                return sqlglot_type(base, register)
            case ArrayType(elemtype=elem):
                return DataType(
                    this=DataType.Type.ARRAY,
                    expressions=[sqlglot_type(elem, register)],
                    nested=True,
                )
            case CompositeType(attributes=attrs):
                return DataType(
                    this=DataType.Type.STRUCT,
                    expressions=[
                        exp.ColumnDef(
                            this=exp.to_identifier(a.name), kind=sqlglot_type(a.attr_type, register)
                        )
                        for a in attrs
                    ],
                    nested=True,
                )
            case t:
                return DataType.build(t.name, dialect="postgres", udt=True)

    def column(attr: Column) -> DataType:
        dt = sqlglot_type(attr.attr_type, register)
        dt.set("nullable", attr.nullable)
        return dt

    mapping: dict[str, dict[str, dict[str, DataType]]] = {}
    for rel in sources(register):
        mapping.setdefault(rel.ns, {})[rel.name] = {k: column(v) for k, v in rel.columns.items()}
    return SearchPathSchema(mapping, search_path)
