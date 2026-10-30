from __future__ import annotations

from typing import TypedDict

from .config import Config
from .drivers.asyncpg import AsyncPGDriver
from .stmt import SQL


class Blacksmith:
    def __init__(self, config: Config):
        self.config = config
        self.book = Book(asyncpg=AsyncPGDriver)

    async def forge(self, sqls: list[SQL]):
        return await self.find_driver().run(self.config, sqls)

    def find_driver(self):
        return self.book[self.config.driver]


class Book(TypedDict):
    asyncpg: type[AsyncPGDriver]
