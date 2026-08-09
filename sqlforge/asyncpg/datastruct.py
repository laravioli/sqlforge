from dataclasses import dataclass

from asyncpg.prepared_stmt import PreparedStatement

from sqlforge.datastruct import TransformedSQL


@dataclass(frozen=True)
class PreparedSql(TransformedSQL):
    prepared: PreparedStatement
