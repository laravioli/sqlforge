from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer import Scope, build_scope
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.simplify import simplify
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL, TypedSQL

from .catalog import Catalog
from .context import Context
from .exception import Unsupported
from .infer import Analyzer
from .lattice import MAYBE_NULL, Nullability


def using_or_natural(tree: exp.Expr) -> bool:
    """Any USING or NATURAL join in the statement? (qualify rewrites them into ON, so check first.)"""
    return any(
        join.args.get("using") or join.method == "NATURAL" for join in tree.find_all(exp.Join)
    )


BYPASS: list[Callable[[exp.Expr], bool]] = [using_or_natural]


def bypass(ast: exp.Expr):
    return any(fn(ast) for fn in BYPASS)


def prepare_sql(sql: SQL, schema: MappingSchema) -> Scope:
    ast = sql.expr.copy().unnest()
    scope = None

    if not bypass(ast):
        ast = simplify(
            annotate_types(
                qualify(ast, schema=schema, dialect="postgres"),
                schema=schema,
                dialect="postgres",
            ),
            dialect="postgres",
        )
        scope = build_scope(ast)

    if scope is None:
        raise Unsupported(f"{sql.name} is not supported by null engine")

    return scope


@dataclass(frozen=True)
class Analysis:
    columns: tuple[ColumnResult, ...]
    error: str | None = None


@dataclass(frozen=True)
class ColumnResult:
    name: str
    type: str
    nullability: Nullability

    @property
    def python(self) -> str:
        return self.nullability.python(self.type)


class Engine:
    def __init__(self, catalog: Catalog, statements: list[TypedSQL]):
        self.catalog = catalog
        self.statements = statements

    def analyze(self):
        return [self.analyze_one(stmt) for stmt in self.statements]

    def analyze_one(self, statement: TypedSQL) -> Analysis:
        attrs = list(statement.typed_attrs.items())
        if not attrs:
            return Analysis(columns=())

        try:
            error = None
            scope = prepare_sql(statement.source, self.catalog.mapping_schema)

            nulls = Analyzer(Context(), self.catalog).run(scope)
            if len(attrs) != len(nulls):
                raise Unsupported

        except (SqlglotError, Unsupported) as e:
            nulls, error = [MAYBE_NULL] * len(attrs), str(e)

        return Analysis(
            columns=tuple(
                ColumnResult(name, type_, null) for (name, type_), null in zip(attrs, nulls)
            ),
            error=error,
        )
