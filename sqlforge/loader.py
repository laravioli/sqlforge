from __future__ import annotations

import re
from keyword import iskeyword
from pathlib import Path

from sqlglot import ParseError, TokenError, exp, parse

from .config import Config
from .errors import LoaderError
from .structures import *

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


# Loader


def load_sql(cfg: Config) -> list[SQL]:
    sqls: list[SQL] = []
    for s in cfg.sources:
        sqls.extend(_load_from_source(s))
    return sqls


def _load_from_source(src: Path) -> list[SQL]:
    if src.is_file():
        return _load_file(src, src)

    return [sql for f in sorted(src.rglob("*.sql")) for sql in _load_file(src, f)]


def _load_file(src: Path, file: Path) -> list[SQL]:
    try:
        exprs = parse(file.read_text(encoding="utf-8"), dialect="postgres")
    except (ParseError, TokenError, UnicodeDecodeError) as e:
        raise LoaderError(f"{file}: {e}") from e

    exprs = [e for e in exprs if e is not None]
    sqls = [_load_query(e, Origin(src, file, i)) for i, e in enumerate(exprs)]
    _check_dup_name(file, sqls)

    return sqls


def _load_query(expr: exp.Expr, origin: Origin):
    target: exp.Expr = expr.args.get("with_") or expr
    while not target.comments and isinstance(target, (exp.SetOperation, exp.Subquery)):
        target = target.this

    for com in target.comments or []:
        if match := META_PATTERN.fullmatch(com.strip()):  # match the first meta_pattern
            target.comments = []
            return SQL(
                name=_validate_name(match["name"], origin),
                origin=origin,
                kind=_validate_kind(match["kind"], origin),
                expr=expr,
            )

    raise LoaderError(
        f'{origin}: missing metadata comment, expected e.g. "-- name: get_user :one"'
    )


# Validation


def _validate_name(name: str, origin: Origin):
    if not name.isidentifier() or iskeyword(name.lower()):
        raise LoaderError(f"{origin}: {name!r} is not a valid function name")
    return name


def _validate_kind(kind: str, origin: Origin):
    try:
        query_kind = QueryKind(kind)
    except ValueError:
        valid = ", ".join(k.value for k in QueryKind)
        raise LoaderError(
            f"{origin}: unknown kind {kind!r} (expected one of: {valid})"
        ) from None
    return query_kind


def _check_dup_name(filepath: Path, sqls: list[SQL]):
    seen = set()
    for sql in sqls:
        name = sql.name.lower()
        if name in seen:
            raise LoaderError(f"{filepath}: duplicate query name {sql.name!r}")
        seen.add(name)
