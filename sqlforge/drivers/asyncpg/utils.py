import keyword
from contextlib import asynccontextmanager
from typing import cast

import asyncpg

# Connection


@asynccontextmanager
async def get_conn(dsn: str):
    conn = await asyncpg.connect(dsn=dsn, server_settings={"jit": "off"})
    try:
        yield cast(asyncpg.Connection, conn)
    finally:
        await conn.close()


def isidentifier(ident: str) -> bool:
    return ident.isidentifier() and not keyword.iskeyword(ident)
