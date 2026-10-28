import re
from keyword import iskeyword
from pathlib import Path

from sqlglot import Expr, parse

from .config import Config, get_cfg
from .stmt import SQL, QueryKind

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
        self.cfg_path, self.cfg = get_cfg(search_start)
        self.registry: dict[Path, str] = {}

    def load_query(self):
        pass


# impl
def load_queries(config: Config) -> list[SQL]:
    with open(config.inputs[0], "r") as file:
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
