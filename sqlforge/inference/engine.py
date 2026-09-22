from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL
from sqlforge.introspection.schemas import SchemaGenerator
from sqlforge.introspection.structures import PGTypeRegister

from .infer import ScopedSQL
from .lattice import NullSet


@dataclass(frozen=True)
class InferredSQL:
    source: SQL
    nullable: Sequence[tuple[str, NullSet]]


# TODO consider the impact of parameters nullability (in select column its obvious : select $1)
# TODO could also happen in predicate (or $1)
class Engine:
    def __init__(self, type_register: PGTypeRegister | None = None, schema: dict | None = None):
        if type_register is not None:
            self.schema = SchemaGenerator(register=type_register).gen()
        else:
            self.schema = MappingSchema(schema=schema)

    def infer(self, queries: list[SQL]):
        nb = len(queries)
        counter = 1
        output: list[InferredSQL] = []
        for query in queries:
            inferred = None
            try:
                inferred = self.infer_one(query)
                output.append(inferred)
            except Exception as e:  # noqa: BLE001
                print(e)
            finally:
                print(f"{counter} / {nb}")
                # print(query)
                if inferred:
                    print(inferred.nullable)
                # print("\n")
                counter += 1

        return output

    def infer_one(self, query: SQL):
        return InferredSQL(
            source=query,
            nullable=ScopedSQL.root(query, self.schema, full_optimize=False).infer().unwrap(),
        )
