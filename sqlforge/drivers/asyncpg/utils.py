import keyword
from contextlib import asynccontextmanager
from typing import cast

import asyncpg

# Connection


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


def isidentifier(ident: str) -> bool:
    return ident.isidentifier() and not keyword.iskeyword(ident)
