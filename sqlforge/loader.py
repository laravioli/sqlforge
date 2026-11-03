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
    files = _validate_files(src, [src] if src.is_file() else sorted(src.rglob("*.sql")))
    return [sql for f in files for sql in _load_file(src, f)]


def _load_file(src: Path, file: Path) -> list[SQL]:
    try:
        exprs = parse(file.read_text(encoding="utf-8"), dialect="postgres")
    except (ParseError, TokenError, UnicodeDecodeError) as e:
        raise LoaderError(f"{file}: {e}") from e

    exprs = [e for e in exprs if e is not None and not isinstance(e, exp.Semicolon)]
    sqls = [_load_query(e, Origin(src, file, i)) for i, e in enumerate(exprs)]
    _check_fn_dup_name(file, sqls)

    return sqls


def _load_query(expr: exp.Expr, origin: Origin):
    target: exp.Expr = expr.args.get("with_") or expr
    while not target.comments and isinstance(target, (exp.SetOperation, exp.Subquery)):
        target = target.this

    for com in target.comments or []:
        if match := META_PATTERN.fullmatch(com.strip()):  # match the first meta_pattern
            target.comments = []
            return SQL(
                name=_validate_fn_name(match["name"], origin),
                origin=origin,
                kind=_validate_fn_kind(match["kind"], origin),
                expr=expr,
            )

    raise LoaderError(
        f'{origin}: missing metadata comment, expected e.g. "-- name: get_user :one"'
    )


# Validation


def _validate_files(src: Path, files: list[Path]):
    for file in files:
        parts = file.relative_to(src.parent).with_suffix("").parts
        if not all(n.isidentifier() and not iskeyword(n) for n in parts):
            raise LoaderError(f"{file}: {'.'.join(parts)} is not an importable module")

    return files


def _validate_fn_name(name: str, origin: Origin):
    if not name.isidentifier() or iskeyword(name.lower()):
        raise LoaderError(f"{origin}: {name!r} is not a valid function name")
    return name


def _validate_fn_kind(kind: str, origin: Origin):
    try:
        query_kind = QueryKind(kind)
    except ValueError:
        valid = ", ".join(k.value for k in QueryKind)
        raise LoaderError(
            f"{origin}: unknown kind {kind!r} (expected one of: {valid})"
        ) from None
    return query_kind


def _check_fn_dup_name(filepath: Path, sqls: list[SQL]):
    seen = set()
    for sql in sqls:
        name = sql.name.lower()
        if name in seen:
            raise LoaderError(f"{filepath}: duplicate query name {sql.name!r}")
        seen.add(name)
