import re
from keyword import iskeyword

from sqlglot import Expr, parse

from sqlforge.datastruct import SQL, QueryKind

from .core import Config, Info

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


# impl
def load(config: Config, info: Info) -> list[SQL]:
    with open(config.path) as file:
        content = file.read()
        dialect = info["dialect"]
        sqls = parse(content, dialect=dialect)

    return [load_query(sql, dialect) for sql in sqls if sql]


def load_query(expr: Expr, dialect) -> SQL:
    target: Expr = expr.args.get("with_") or expr

    if not target.comments:
        raise ValueError("Unable to find metadata")

    for com in target.comments:
        if pattern := META_PATTERN.match(com.strip()):  # match the first meta_pattern
            groups = pattern.groupdict()
            name: str = groups["name"]
            validate_query_name(name)
            # raise if not convertible
            kind = QueryKind(groups["kind"])
            # all information should be extracted before this point
            target.comments = []
            return SQL(name=name, kind=kind, expr=expr, dialect=dialect)

    raise ValueError("Unable to parse metadata")


def validate_query_name(name: str):
    if not name.isidentifier() or iskeyword(name):
        raise ValueError(f"{name} is not a valid function name")
