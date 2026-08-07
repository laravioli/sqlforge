from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, TypedDict

type Driver = Literal["asyncpg"]


@dataclass(frozen=True)
class Config:
    path: Path
    dsn: str  # postgres://user:password@host:port/db
    driver: Driver


class Info(TypedDict):
    dialect: str


class Recipe(ABC):
    config: Config
    info: ClassVar[Info]

    @classmethod
    @abstractmethod
    async def run(cls, cfg: Config) -> Any: ...
