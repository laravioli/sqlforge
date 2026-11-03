from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Protocol

from sqlforge.inference.structures import AnalyzedSQL
from sqlforge.introspection.structures import Oid, PGTypeRegister
from sqlforge.utils import normalize_name

from .base import Text


class Output(Protocol):
    @property
    def out(self) -> Path: ...

    @property
    def content(self) -> Text: ...


@dataclass(frozen=True, slots=True)
class File:
    src: Path
    file: Path
    content: Text

    @property
    def out(self):
        return self.file.with_suffix(".py").relative_to(self.src.parent)

    @staticmethod
    def groups(sqls: list[AnalyzedSQL]):
        groups: dict[Path, list[AnalyzedSQL]] = defaultdict(list)

        for sql in sqls:
            groups[sql.origin.file].append(sql)

        return groups


@dataclass(frozen=True, slots=True)
class Schema:
    out: Path
    content: Text

    @classmethod
    def make(cls, ns: str, content: Text) -> Schema:
        return cls(Path("schema") / f"{normalize_name(ns)}.py", content)


type PythonType = PythonRegularType | PythonArrayType | PythonRangeType
type PythonTypeRegister = dict[Oid, PythonType]


@dataclass(frozen=True)
class PythonRegularType:
    hint: str
    ns: str | None = None

    @cached_property
    def qualified_hint(self):
        return (
            f"{normalize_name(self.ns)}.{self.hint}"
            if self.ns is not None
            else self.hint
        )


PYTHON_ANY = PythonRegularType(hint="typing.Any")


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


@dataclass(frozen=True)
class DriverCtx:
    pg_types: PGTypeRegister
    python_types: PythonTypeRegister
    default_import: Sequence[str]

    @cached_property
    def schema_import(self):
        return tuple(
            sorted({v.ns for v in self.pg_types.values() if v.is_user_defined})
        )

    @cached_property
    def normalized_schema_import(self):
        return tuple(normalize_name(n) for n in self.schema_import)
