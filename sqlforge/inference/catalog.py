from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlglot.schema import MappingSchema

from sqlforge.introspection.schemas import Table, mapping_schema, user_tables
from sqlforge.introspection.structures import PGTypeRegister


@dataclass(init=False)
class Catalog:
    tables: Mapping[str, Table]
    mapping_schema: MappingSchema

    def __init__(
        self,
        type_register: PGTypeRegister | None = None,
        schema: dict | None = None,
        tables: dict[str, Table] | None = None,
    ):

        if type_register is not None:
            self.tables = user_tables(register=type_register)
            self.mapping_schema = mapping_schema(register=type_register)

        else:
            if tables is None:
                raise ValueError()

            self.tables = tables
            self.mapping_schema = MappingSchema(schema=schema, dialect="postgres")

    def add_view(self):
        pass
