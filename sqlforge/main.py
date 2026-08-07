from __future__ import annotations

from typing import TypedDict

from sqlforge.asyncpg import APGRecipe

from .core import Config


class Book(TypedDict):
    asyncpg: type[APGRecipe]


class Blacksmith:
    def __init__(self, config: Config):
        self.config = config
        self.book = Book(asyncpg=APGRecipe)

    async def forge(self):
        return await self.find_recipe().run(self.config)

    def find_recipe(self):
        return self.book[self.config.driver]
