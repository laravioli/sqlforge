from __future__ import annotations

from typing import TypeIs

from sqlglot import exp
from sqlglot.optimizer.simplify import extract_date

NON_NULL_CONSTANT = (exp.Literal, exp.Boolean)
CONSTANT = (*NON_NULL_CONSTANT, exp.Null)

BOOLEAN_EXPRESSION = (exp.Predicate, exp.Connector, exp.Boolean, exp.Not)
COMPARISON_OPERATOR = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)

type Comparison = exp.EQ | exp.NEQ | exp.GT | exp.GTE | exp.LT | exp.LTE


def is_non_null_constant(expression: exp.Expr) -> bool:
    expression = expression.this if isinstance(expression, exp.Neg) else expression
    return isinstance(expression, NON_NULL_CONSTANT) or extract_date(expression) is not None


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
    return isinstance(expression, exp.Anonymous) and expression.this == "row"
