from __future__ import annotations

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
    if isinstance(e, exp.DPipe):
        return _is_known_non_array(e.this, e.expression)
    return isinstance(e, STRICT_BINARY)


def _is_known_non_array(*operands: exp.Expr) -> bool:
    for o in operands:
        ty = o.type
        if (
            ty is None
            or ty.this in (exp.DataType.Type.UNKNOWN, exp.DataType.Type.ARRAY)
            or ty.is_type("array")
        ):
            return False
    return True


def is_single_row(select: exp.Expr) -> bool:
    """An aggregate query without GROUP BY / HAVING / LIMIT / OFFSET returns exactly one row,
    whatever FROM and WHERE produce."""
    if not isinstance(select, exp.Select):
        return False
    if any(select.args.get(k) for k in ("group", "having", "limit", "offset")):
        return False
    return any(
        agg.find_ancestor(exp.Select) is select and not isinstance(agg.parent, exp.Window)
        for p in select.expressions
        for agg in p.find_all(exp.AggFunc)
    )
