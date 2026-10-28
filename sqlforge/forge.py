from __future__ import annotations

from typing import TypedDict

from .config import Config
from .drivers.asyncpg import AsyncPGDriver


class Blacksmith:
    def __init__(self, config: Config):
        self.config = config
        self.book = Book(asyncpg=AsyncPGDriver)

    async def forge(self):
        return await self.find_recipe().run(self.config)

    def find_recipe(self):
        return self.book[self.config.driver]


class Book(TypedDict):
    asyncpg: type[AsyncPGDriver]
