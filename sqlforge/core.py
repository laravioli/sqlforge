from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cached_property
from inspect import isawaitable
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

    @cached_property
    @abstractmethod
    def pipeline(self) -> Pipeline[[Config, Info], Any]: ...

    async def apply(self):
        return await self.pipeline.apply(self.config, self.info)


type StepResult[T] = T | Awaitable[T]


async def resolve[T](value: StepResult[T]) -> T:
    if isawaitable(value):
        return await value
    return value


# NOTE this version preserve type relation vs tuple[Callable,...]
@dataclass(frozen=True)
class Pipeline[**P, R]:
    _fn: Callable[P, StepResult[R]]

    async def apply(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return await resolve(self._fn(*args, **kwargs))

    def add[S](self, fn: Callable[[R], StepResult[S]]) -> Pipeline[P, S]:
        async def pipe(*args: P.args, **kwargs: P.kwargs) -> S:
            ret = await self.apply(*args, **kwargs)
            return await resolve(fn(ret))

        return Pipeline(_fn=pipe)

    @staticmethod
    def start[**A](fn: Callable[A, StepResult[R]]) -> Pipeline[A, R]:
        return Pipeline(_fn=fn)
