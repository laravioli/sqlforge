from __future__ import annotations

from collections.abc import Callable

from sqlglot import exp, parse_one
from sqlglot.optimizer import Scope, build_scope
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.simplify import simplify_parens
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL
from sqlforge.introspection.catalog import View

from .exception import ByPassed, Unsupported
from .expressions import COMPARISON_PREDICATES


def not_query(ast: exp.Expr) -> bool:
    return not isinstance(ast, exp.Query)


def contain_dml(ast: exp.Expr) -> bool:
    return bool(ast.find(exp.Insert, exp.Update, exp.Delete, exp.Merge))


def is_recursive(ast: exp.Expr) -> bool:
    """WITH RECURSIVE isn't analyzed yet"""
    return any(w.args.get("recursive") for w in ast.find_all(exp.With))


def has_grouping_sets(ast: exp.Expr) -> bool:
    return bool(ast.find(exp.Rollup, exp.Cube, exp.GroupingSets))


def is_after_comparison(ast: exp.Expr) -> bool:
    # https://github.com/tobymao/sqlglot/issues/8661
    """`a = b IS NULL` is `(a = b) IS NULL` in Postgres, but sqlglot parses `a = (b IS NULL)`"""
    for cmp in ast.find_all(*COMPARISON_PREDICATES):
        right = cmp.expression.this if isinstance(cmp.expression, exp.Not) else cmp.expression
        if isinstance(right, (exp.Is, exp.NullSafeEQ, exp.NullSafeNEQ)):
            return True
    return False


BYPASS: list[Callable[[exp.Expr], bool]] = [
    not_query,
    contain_dml,
    is_recursive,
    has_grouping_sets,
    is_after_comparison,
]


def bypass(ast: exp.Expr):
    return any(fn(ast) for fn in BYPASS)


def _simplify_parens(ast: exp.Expr) -> exp.Expr:
    """only sqlglot's paren rule of simplify, bottom-up: drops the parens SQL doesn't need"""
    for paren in reversed(list(ast.find_all(exp.Paren, bfs=False))):
        paren.replace(simplify_parens(paren, "postgres"))
    return ast


def _prepare(ast: exp.Expr, name: str, schema: MappingSchema) -> Scope:
    scope = None

    if bypass(ast):
        raise ByPassed("The analyzer does not support this statement yet")

    scope = build_scope(_simplify_parens(qualify(ast, schema=schema, dialect="postgres")))

    if scope is None:
        raise Unsupported(f"{name} could not create a sqlglot scope")

    return scope


def prepare_sql(sql: SQL, schema: MappingSchema) -> Scope:
    return _prepare(sql.expr.copy().unnest(), sql.name, schema)


def prepare_view(view: View, schema: MappingSchema) -> Scope:
    ast = parse_one(view.query, dialect="postgres")
    return _prepare(ast.unnest(), view.name, schema)
