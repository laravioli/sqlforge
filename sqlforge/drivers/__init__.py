from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlforge.config import Config


class Driver(ABC):
    config: Config

    @classmethod
    @abstractmethod
    async def run(cls, cfg: Config) -> Any: ...
