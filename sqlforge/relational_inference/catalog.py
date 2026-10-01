from __future__ import annotations

from dataclasses import dataclass

from sqlglot.schema import MappingSchema

from sqlforge.introspection.schemas import mapping_schema
from sqlforge.introspection.structures import PGTypeRegister


@dataclass(init=False)
class Catalog:
    tables: dict[str, Table]
    mapping_schema: MappingSchema

    def __init__(self, type_register: PGTypeRegister | None = None, schema: dict | None = None):
        if type_register is not None:
            self.mapping_schema = mapping_schema(register=type_register)

        else:
            self.mapping_schema = MappingSchema(schema=schema, dialect="postgres")


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class Table:
    name: str
    columns: dict[str, Column]

    def get(self, column: str):
        return self.columns[column]
