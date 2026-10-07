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


def not_query(ast: exp.Expr) -> bool:
    return not isinstance(ast, exp.Query)


def contain_dml(ast: exp.Expr) -> bool:
    return bool(ast.find(exp.Insert, exp.Update, exp.Delete, exp.Merge))


# https://github.com/tobymao/sqlglot/issues/8516
def using_or_natural(ast: exp.Expr) -> bool:
    """Any USING or NATURAL join in the statement? (qualify rewrites them into ON, so check first.)"""
    return any(
        join.args.get("using") or join.method == "NATURAL" for join in ast.find_all(exp.Join)
    )


BYPASS: list[Callable[[exp.Expr], bool]] = [not_query, contain_dml, using_or_natural]


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
        raise Unsupported(f"{sql.name} could not create a sqlglot scope")

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

            nulls = Analyzer(Context(), self.catalog).run(scope).result()
            if len(attrs) != len(nulls):
                raise Unsupported(f"{len(nulls)} columns inferred, {len(attrs)} expected")

        except (SqlglotError, Unsupported) as e:
            nulls, error = [MAYBE_NULL] * len(attrs), str(e)

        return Analysis(
            columns=tuple(
                ColumnResult(name, type_, null) for (name, type_), null in zip(attrs, nulls)
            ),
            error=error,
        )
