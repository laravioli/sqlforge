from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum, StrEnum, auto
from keyword import iskeyword
from pathlib import Path

from sqlglot import Expr, parse

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


class Loader:
    def __init__(self, search_start: Path | None = None):
        self.registry: dict[Path, str] = {}

    def load_query(self):
        pass


# impl
def load_queries(config: Config) -> list[SQL]:
    with open(config.sources[0], "r") as file:
        content = file.read()
        sqls = parse(content, dialect="postgres")

    return [load_query(sql, "postgres") for sql in sqls if sql]


def load_query(expr: Expr, dialect) -> SQL:
    target: Expr = expr.args.get("with_") or expr

    if not target.comments:
        raise LoaderError("Unable to find metadata")

    for com in target.comments:
        if pattern := META_PATTERN.match(com.strip()):  # match the first meta_pattern
            groups = pattern.groupdict()
            name: str = groups["name"]
            validate_query_name(name)
            # raise if not convertible
            kind = QueryKind(groups["kind"])
            # all information should be extracted before this point
            target.comments = []
            return SQL(name=name, kind=kind, expr=expr)

    raise LoaderError("Unable to parse metadata")


def validate_query_name(name: str):
    if not name.isidentifier() or iskeyword(name):
        raise LoaderError(f"{name} is not a valid function name")


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
    path: Path
    index: int


@dataclass(frozen=True)
class SQL:
    name: str
    kind: QueryKind
    expr: Expr

    def __str__(self):
        return self.expr.sql(dialect="postgres")

    def copy(self):
        return replace(self, expr=self.expr.copy())


@dataclass(frozen=True)
class TransformedSQL:
    source: SQL
    params: dict[str, int]


@dataclass(frozen=True)
class TypedSQL:
    source: SQL
    typed_params: dict[ParamName, PythonType]
    typed_attrs: list[tuple[AttrName, PythonType]]

    @property
    def name(self):
        return self.source.name
