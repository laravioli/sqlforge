from __future__ import annotations

from dataclasses import dataclass

from sqlforge.core.structures import SQL
from sqlforge.postgres.schemas import SchemaGenerator
from sqlforge.postgres.structures import PGTypeRegister

from .infer import ScopedSQL
from .lattice import NullSet


@dataclass(frozen=True)
class InferredSQL:
    source: SQL
    nullable: dict[str, bool]


# TODO consider the impact of parameters nullability (in select column its obvious : select $1)
# TODO could also happen in predicate (or $1)
class Engine:
    def __init__(self, type_register: PGTypeRegister):
        self.schema = SchemaGenerator(register=type_register).gen()

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
            nullable=transform_null(
                ScopedSQL.root(query, self.schema, full_optimize=False).infer()
            ),
        )


def transform_null(null: dict[str, NullSet]) -> dict[str, bool]:
    return {k: bool(v) for k, v in null.items()}
