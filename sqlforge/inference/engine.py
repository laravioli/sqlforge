from __future__ import annotations

from dataclasses import dataclass

from sqlforge.core.structures import SQL
from sqlforge.postgres.schemas import SchemaGenerator
from sqlforge.postgres.structures import PGTypeRegister

from .enums import Nullability
from .infer import ScopedSQL


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
        output: list[InferredSQL] = []
        for query in queries:
            try:
                output.append(self.infer_one(query))
            except Exception as e:  # noqa: BLE001
                print(e, query, "\n")
        return output

    def infer_one(self, query: SQL):
        return InferredSQL(
            source=query, nullable=transform_null(ScopedSQL.make(query, self.schema).infer())
        )


def transform_null(null: dict[str, Nullability]) -> dict[str, bool]:
    return {k: bool(v) for k, v in null.items()}
