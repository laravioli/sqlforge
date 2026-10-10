from __future__ import annotations

from collections.abc import Iterator
from typing import TypeIs

from sqlglot import exp
from sqlglot.optimizer.simplify import extract_date

BOOLEAN_EXPRESSION = (exp.Predicate, exp.Connector, exp.Boolean, exp.Not)
COMPARISON_OPERATOR = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)

STRICT_BINARY = (
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.IntDiv,
    exp.Pow,
    exp.BitwiseAnd,
    exp.BitwiseOr,
    exp.BitwiseXor,
    exp.BitwiseLeftShift,
    exp.BitwiseRightShift,
)
type Comparison = exp.EQ | exp.NEQ | exp.GT | exp.GTE | exp.LT | exp.LTE


def is_non_null_constant(expression: exp.Expr) -> bool:
    while isinstance(expression, (exp.Neg, exp.Paren)):
        expression = expression.this
    if isinstance(expression, (exp.Literal, exp.Boolean)):
        return True
    if isinstance(expression, exp.Interval):
        return is_non_null_constant(expression.this)
    return extract_date(expression) is not None


def is_boolean_expr(expression: exp.Expr):
    return isinstance(expression, BOOLEAN_EXPRESSION)


def is_comparison_operator(
    expression: exp.Expr,
) -> TypeIs[Comparison]:
    return isinstance(expression, COMPARISON_OPERATOR)


def is_subquery_predicate(expression: exp.Expr) -> TypeIs[exp.Any | exp.All | exp.Exists | exp.In]:
    return isinstance(expression, (exp.Any, exp.All, exp.Exists, exp.In))


def is_true(expression: exp.Expr) -> bool:
    return type(expression) is exp.Boolean and expression.this


def is_row(expression: exp.Expr) -> bool:
    return isinstance(expression, exp.Anonymous) and expression.name.lower() == "row"


def is_join_group(node: exp.Expr) -> bool:
    return isinstance(node, exp.Subquery) and not (
        node.alias or isinstance(node.this, exp.UNWRAPPED_QUERIES)
    )


def is_strict_binary(e: exp.Expr) -> bool:
    return isinstance(e, STRICT_BINARY)


def is_plain_aggregate(select: exp.Select, aggregates: frozenset[str] | None = None) -> bool:
    group = select.args.get("group")
    if group is not None:  # GROUP BY () is one group, any other GROUP BY one row per group
        return all(isinstance(g, exp.Tuple) and not g.expressions for g in group.expressions)
    if select.args.get("having"):
        return True
    clauses = (
        *select.expressions,
        select.args.get("order"),
        select.args.get("distinct"),
        *(select.args.get("windows") or ()),
    )
    return any(
        not _is_window_call(f)
        and (isinstance(f, exp.AggFunc) or aggregates is None or f.name.lower() in aggregates)
        for clause in clauses
        if clause is not None
        for f in _own_calls(clause)
    )


def _own_calls(node: exp.Expr) -> Iterator[exp.Expr]:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, (exp.AggFunc, exp.Anonymous)):
            yield n
        stack.extend(c for c in n.iter_expressions() if not isinstance(c, exp.Query))


def _is_window_call(f: exp.Expr) -> bool:
    node = f.parent if isinstance(f.parent, exp.Filter) else f
    return isinstance(node.parent, exp.Window) and node.arg_key == "this"
