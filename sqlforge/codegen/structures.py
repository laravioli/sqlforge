from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
    _gen: Callable[[File, str], Text]
    _schema_import: str

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
