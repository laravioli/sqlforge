from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import cast

import asyncpg
from asyncpg.prepared_stmt import PreparedStatement
from msgspec.json import Decoder

from sqlforge.errors import IntrospectionError
from sqlforge.structures import QueryKind, TransformedSQL

from .stmt import LOOKUP_TYPES, RESULT_TYPES, TYPE_ENUM, USER_TYPE_OIDS
from .structures import (
    ArrayType,
    BaseType,
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGAttribute,
    PGTypeRegister,
    PreparedSQL,
    PseudoType,
    RangeType,
    TypeKind,
    TypeRecord,
    ViewType,
)

_ATTR_DECODER = Decoder(type=list[PGAttribute])
_PREPARE_ERRORS = (
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
    asyncpg.InternalClientError,
)
_NO_ROWS = (QueryKind.EXEC, QueryKind.EXECMANY)


class Fetcher:
    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    @classmethod
    async def fetch(cls, dsn: str | None, transformed: list[TransformedSQL]):
        async with get_conn(dsn) as conn:
            fetcher = cls(conn)
            return await fetcher._fetch(transformed)

    async def _fetch(
        self, transformed: list[TransformedSQL]
    ) -> tuple[PGTypeRegister, list[PreparedSQL]]:
        prepared = await self._prepare_stmts(transformed)
        pg_types = await self._fetch_types(
            set().union(*(stmt.oids for stmt in prepared))
            | set(await self._conn.fetchval(USER_TYPE_OIDS))
        )
        return pg_types, prepared

    async def _prepare_stmts(self, sqls: list[TransformedSQL]):
        # this way prepared stmt are not gc'ed, avoiding I/O from asyncpg
        self._stmts: list[PreparedStatement] = []
        for sql in sqls:
            try:
                stmt = await self._conn.prepare(sql.text)
            except _PREPARE_ERRORS as e:
                raise IntrospectionError(f"{sql.origin}: {e}") from e
            if not stmt.get_attributes() and sql.kind not in _NO_ROWS:
                raise IntrospectionError(f"{sql.origin}: returns no column, use :exec")
            self._stmts.append(stmt)

        result_oids = await self._result_oids([stmt.get_name() for stmt in self._stmts])
        return [
            PreparedSQL(
                source,
                [param.oid for param in prepared.get_parameters()],
                _stmt_result_oids(prepared, result_oids),
                [attr.name for attr in prepared.get_attributes()],
            )
            for source, prepared in zip(sqls, self._stmts)
        ]

    async def _result_oids(self, names: Sequence[str]) -> dict[str, list[Oid]] | None:
        if self._conn.get_server_version() < (16,):
            return None
        records = await self._conn.fetch(RESULT_TYPES, names)
        return {r["name"]: r["result_types"] for r in records}

    async def _fetch_types(self, oids: set[int]):
        records = cast(list[TypeRecord], await self._conn.fetch(LOOKUP_TYPES, oids))
        enums = {r["oid"]: r["values"] for r in await self._conn.fetch(TYPE_ENUM)}
        return _convert_type_records(records, enums)


def _convert_type_records(
    recs: list[TypeRecord], enums: dict[Oid, list[str]]
) -> PGTypeRegister:

    register: PGTypeRegister = {}

    for rec in recs:
        kind = TypeKind(rec["kind"].decode())
        match kind:
            case TypeKind.BASE:
                # arrays are base types with typcategory 'A'; typelem alone also matches name, point
                cls = ArrayType if rec["category"] == "A" else BaseType
                register[rec["oid"]] = cls.convert(rec, kind=kind)

            case TypeKind.COMPOSITE:
                assert rec["comp_kind"] is not None
                attributes = (
                    _ATTR_DECODER.decode(rec["attributes"]) if rec["attributes"] else []
                )
                comp_kind = rec["comp_kind"].decode()

                if comp_kind in ["v", "m"]:
                    register[rec["oid"]] = ViewType.convert(
                        rec,
                        kind=kind,
                        comp_kind=comp_kind,
                        query=rec["query"],
                        attributes=attributes,
                    )
                else:
                    register[rec["oid"]] = CompositeType.convert(
                        rec,
                        kind=kind,
                        comp_kind=comp_kind,
                        attributes=attributes,
                    )

            case TypeKind.DOMAIN:
                register[rec["oid"]] = DomainType.convert(
                    rec,
                    kind=kind,
                )

            case TypeKind.ENUM:
                values = enums.get(rec["oid"], [])

                register[rec["oid"]] = EnumType.convert(
                    rec,
                    kind=kind,
                    values=values,
                )

            case TypeKind.PSEUDO_TYPE:
                register[rec["oid"]] = PseudoType.convert(rec, kind=kind)

            case TypeKind.RANGE | TypeKind.MULTI_RANGE:
                register[rec["oid"]] = RangeType.convert(
                    rec,
                    kind=kind,
                )

    return register


def _stmt_result_oids(
    stmt: PreparedStatement, result_oids: dict[str, list[Oid]] | None
):
    attrs = stmt.get_attributes()
    if result_oids is None:
        oids = [a.type.oid for a in attrs]  # < 16: domains lost (known limitation)
    else:
        oids = result_oids[stmt.get_name()]
    return oids


@asynccontextmanager
async def get_conn(dsn: str | None):
    try:
        conn = await asyncpg.connect(dsn=dsn, server_settings={"jit": "off"})
    except (OSError, asyncpg.PostgresError) as e:
        hint = (
            ""
            if dsn
            else " (no dsn configured; used PG* environment variables and defaults)"
        )
        raise ConnectionError(f"could not connect to PostgreSQL: {e}{hint}") from e
    try:
        yield cast(asyncpg.Connection, conn)
    finally:
        await conn.close()
