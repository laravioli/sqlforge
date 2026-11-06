from __future__ import annotations

from sqlforge.codegen.structures import Output
from sqlforge.config import Config
from sqlforge.inference.engine import Engine
from sqlforge.introspection.fetch import Fetcher
from sqlforge.structures import SQL


class Blacksmith:
    def __init__(self, config: Config):
        self.cfg = config
        match self.cfg.driver:
            case "asyncpg":
                from sqlforge.codegen.asyncpg import AsyncpgCodegen

                from .asyncpg import transform

                self.transform = transform
                self.codegen_class = AsyncpgCodegen

    async def pipeline(self, sqls: list[SQL]) -> list[Output]:
        transformed = [self.transform(sql) for sql in sqls]
        pg_types, prepared = await Fetcher.fetch(self.cfg.dsn, transformed)
        analyzed = Engine(pg_types).analyze(prepared)
        return self.codegen_class(pg_types, self.cfg.format).gen(analyzed)

    @classmethod
    async def forge(cls, cfg: Config, sqls: list[SQL]):
        john_smith = cls(cfg)
        return await john_smith.pipeline(sqls)
