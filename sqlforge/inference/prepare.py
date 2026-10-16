from __future__ import annotations

from collections.abc import Callable

from sqlglot import exp, parse_one
from sqlglot.optimizer import Scope, build_scope
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.simplify import simplify
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL
from sqlforge.introspection.catalog import View

from .exception import ByPassed, Unsupported


def not_query(ast: exp.Expr) -> bool:
    return not isinstance(ast, exp.Query)


def contain_dml(ast: exp.Expr) -> bool:
    return bool(ast.find(exp.Insert, exp.Update, exp.Delete, exp.Merge))


def has_grouping_sets(ast: exp.Expr) -> bool:
    return bool(ast.find(exp.Rollup, exp.Cube, exp.GroupingSets))


BYPASS: list[Callable[[exp.Expr], bool]] = [
    not_query,
    contain_dml,
    has_grouping_sets,
]


def bypass(ast: exp.Expr):
    return any(fn(ast) for fn in BYPASS)


def _prepare(ast: exp.Expr, name: str, schema: MappingSchema) -> Scope:
    scope = None

    if bypass(ast):
        raise ByPassed("The analyzer does not support this statement yet")

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
        raise Unsupported(f"{name} could not create a sqlglot scope")

    return scope


def prepare_sql(sql: SQL, schema: MappingSchema) -> Scope:
    return _prepare(sql.expr.copy().unnest(), sql.name, schema)


def prepare_view(view: View, schema: MappingSchema) -> Scope:
    ast = parse_one(view.query, dialect="postgres")
    return _prepare(ast.unnest(), view.name, schema)
