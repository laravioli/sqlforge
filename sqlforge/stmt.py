from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum, StrEnum, auto
from keyword import iskeyword
from pathlib import Path

from sqlglot import ParseError, TokenError, exp, parse

from .config import Config

type ParamName = str
type AttrName = str
type PythonType = str

# Regex Metadata

H = r"[^\S\r\n]*:[^\S\r\n]*"
METADATA = rf"""
name
{H}
(?P<name>\w+)
{H}
(?P<kind>\w+)
"""
META_PATTERN = re.compile(METADATA, re.VERBOSE)


class LoaderError(Exception): ...


def load_sql(cfg: Config) -> list[SQL]:
    sqls: list[SQL] = []
    for s in cfg.sources:
        sqls.extend(_load_from_source(s))
    return sqls


def _load_from_source(src: Path) -> list[SQL]:
    if src.is_file():
        return _load_file(src.parent, src)

    return [sql for f in sorted(src.rglob("*.sql")) for sql in _load_file(src, f)]


def _load_file(root: Path, file: Path) -> list[SQL]:
    try:
        exprs = parse(file.read_text(encoding="utf-8"), dialect="postgres")
    except (ParseError, TokenError, UnicodeDecodeError) as e:
        raise LoaderError(f"{file}: {e}") from e

    exprs = [e for e in exprs if e is not None]
    return [_load_query(e, Origin(root, file, i)) for i, e in enumerate(exprs)]


def _load_query(expr: exp.Expr, origin: Origin):
    target: exp.Expr = expr.args.get("with_") or expr

    if not target.comments:
        raise LoaderError("Unable to find metadata")

    for com in target.comments or []:
        if match := META_PATTERN.fullmatch(com.strip()):  # match the first meta_pattern
            name, kind = match["name"], match["kind"]
            if not name.isidentifier() or iskeyword(name):
                raise LoaderError(f"{origin}: {name!r} is not a valid function name")
            try:
                query_kind = QueryKind(kind)
            except ValueError:
                valid = ", ".join(k.value for k in QueryKind)
                raise LoaderError(
                    f"{origin}: unknown kind {kind!r} (expected one of: {valid})"
                ) from None

            target.comments = []
            return SQL(name=name, origin=origin, kind=query_kind, expr=expr)

    raise LoaderError(
        f'{origin}: missing metadata comment, expected e.g. "-- name: get_user :one"'
    )


class ParamStyle(Enum):
    QMARK = auto()
    NUMERIC = auto()
    NAMED = auto()
    FORMAT = auto()
    PY_FORMAT = auto()
    DOLLAR = auto()


class QueryKind(StrEnum):
    ONE = "one"  # fetchrow
    MANY = "many"  # fetch
    FETCHMANY = "fetchmany"  # fetchmany
    FETCHVAL = "fetchval"  # fetchval
    EXEC = "exec"  # exec
    EXECMANY = "execmany"  # execmany


@dataclass(frozen=True, slots=True)
class Origin:
    root: Path
    file: Path
    index: int

    @property
    def rel(self) -> Path:
        return self.file.relative_to(self.root)

    def __str__(self) -> str:
        return f"{self.file} (statement {self.index + 1})"


@dataclass(frozen=True, slots=True)
class SQL:
    name: str
    origin: Origin
    kind: QueryKind
    expr: exp.Expr

    def __str__(self):
        return self.expr.sql(dialect="postgres")

    def copy(self):
        return replace(self, expr=self.expr.copy())


@dataclass(frozen=True, slots=True)
class TransformedSQL:
    source: SQL
    params: dict[str, int]

    @property
    def origin(self):
        return self.source.origin


@dataclass(frozen=True, slots=True)
class TypedSQL:
    source: SQL
    typed_params: dict[ParamName, PythonType]
    typed_attrs: list[tuple[AttrName, PythonType]]

    @property
    def name(self):
        return self.source.name

    @property
    def origin(self):
        return self.source.origin
