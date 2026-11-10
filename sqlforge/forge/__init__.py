from __future__ import annotations

from typing import TYPE_CHECKING

from sqlforge.inference.engine import Engine
from sqlforge.introspection.fetch import Fetcher

if TYPE_CHECKING:
    from sqlforge.codegen.structures import Output
    from sqlforge.config import Config
    from sqlforge.structures import SQL


class Blacksmith:
    def __init__(self, config: Config):
        self.cfg = config
        match self.cfg.driver:
            case "asyncpg":
                from .asyncpg import Asyncpg

                self.driver = Asyncpg(config)

    async def pipeline(self, sqls: list[SQL]) -> list[Output]:
        transformed = [self.driver.transform(sql) for sql in sqls]
        pg_types, prepared = await Fetcher.fetch(self.cfg.dsn, transformed)
        engine = Engine(pg_types)
        analyzed = engine.analyze(prepared)
        return self.driver.out(engine.update_views(pg_types), analyzed)

    @classmethod
    async def forge(cls, cfg: Config, sqls: list[SQL]):
        john_smith = cls(cfg)
        return await john_smith.pipeline(sqls)
