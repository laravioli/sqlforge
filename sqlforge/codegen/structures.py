from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol

from sqlforge.inference.structures import AnalyzedSQL

from .base import Text


class Output(Protocol):
    @property
    def out(self) -> Path: ...

    def gen(self) -> Text: ...


@dataclass(frozen=True, slots=True)
class File:
    src: Path
    file: Path
    sqls: list[AnalyzedSQL]
    _gen: Callable[[File, str | None], Text]
    _schema_import: str | None

    @property
    def folder(self):
        return self.file.parent

    @property
    def filename(self):
        return self.file.name

    @property
    def out(self):
        return self.file.with_suffix(".py").relative_to(self.src.parent)

    @property
    def depth(self):
        return len(self.out.parts)

    def gen(self):
        return self._gen(self, self._schema_import)


@dataclass(frozen=True, slots=True)
class Schema:
    out: Path
    _gen: Callable

    def gen(self):
        return self._gen()


type PythonType = PythonRegularType | PythonArrayType | PythonRangeType


@dataclass(frozen=True)
class PythonRegularType:
    hint: str
    ns: str | None = None

    @cached_property
    def qualified_hint(self):
        return f"{self.ns}.{self.hint}" if self.ns is not None else self.hint


@dataclass(frozen=True)
class PythonArrayType:
    inner: PythonType

    @cached_property
    def hint(self):
        return f"list[{self.inner.hint} | None]"

    @cached_property
    def qualified_hint(self):
        return f"list[{self.inner.qualified_hint} | None]"

    @cached_property
    def ns(self):
        return self.inner.ns


@dataclass(frozen=True)
class PythonRangeType:
    inner: PythonType
    multirange: bool

    @cached_property
    def hint(self):
        rng = f"asyncpg.Range[{self.inner.hint}]"
        return f"list[{rng}]" if self.multirange else rng

    @cached_property
    def qualified_hint(self):
        rng = f"asyncpg.Range[{self.inner.qualified_hint}]"
        return f"list[{rng}]" if self.multirange else rng

    @cached_property
    def ns(self):
        return self.inner.ns
