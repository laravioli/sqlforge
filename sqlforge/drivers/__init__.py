from __future__ import annotations

from abc import ABC, abstractmethod

from sqlforge.codegen.structures import Output
from sqlforge.config import Config
from sqlforge.stmt import SQL


class Driver(ABC):
    config: Config

    @classmethod
    @abstractmethod
    async def run(cls, cfg: Config, sqls: list[SQL]) -> list[Output]: ...
