from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeIs

from sqlglot import exp
from sqlglot.optimizer.simplify import extract_date

from .lattice import BooleanSet, NullSet

# 5. COALESCE
# 6. CASE
# 7. Basic operators
# 8. Aggregates
# 9. UNION
# 10. Dialect-specific functions


class SimplificationError(Exception):
    pass


# ╔══════════════════════════════════════╗
# ║          Classification              ║
# ╚══════════════════════════════════════╝

NON_NULL_CONSTANT = (exp.Literal, exp.Boolean)
CONSTANT = (*NON_NULL_CONSTANT, exp.Null)

BOOLEAN_EXPRESSION = (exp.Predicate, exp.Connector, exp.Boolean, exp.Not)


# Although COALESCE, GREATEST, and LEAST are syntactically similar to functions, they are
# not ordinary functions, and thus cannot be used with explicit VARIADIC array arguments.
# NOTE: should handle them carefully

# NOTE: subquery predicate
# NOTE: conditional structure (case, coalesce)
# NOTE: strict vs non strict function
# NOTE: cast
# NOTE: rows


def is_non_null_constant(expression: exp.Expr) -> bool:
    expression = expression.this if isinstance(expression, exp.Neg) else expression
    return isinstance(expression, NON_NULL_CONSTANT) or extract_date(expression) is not None


def is_boolean_expr(expression: exp.Expr):
    return isinstance(expression, BOOLEAN_EXPRESSION)


def is_logical(expression: exp.Expr) -> TypeIs[exp.And | exp.Or | exp.Not]:
    return isinstance(expression, (exp.And, exp.Or, exp.Not))


def is_comparison_operator(
    expression: exp.Expr,
) -> TypeIs[exp.EQ | exp.NEQ | exp.GT | exp.GTE | exp.LT | exp.LTE]:
    return isinstance(expression, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE))


def is_subquery_predicate(expression: exp.Expr) -> TypeIs[exp.Any | exp.All | exp.Exists | exp.In]:
    return isinstance(expression, (exp.Any, exp.All, exp.Exists, exp.In))


def is_true(expression: exp.Expr) -> bool:
    return type(expression) is exp.Boolean and expression.this


def is_null(expression: exp.Expr) -> TypeIs[exp.Null]:
    return type(expression) is exp.Null


def is_row(expression: exp.Expr) -> bool:
    return isinstance(expression, exp.Anonymous) and expression.this == "row"


# ╔══════════════════════════════════════╗
# ║          Inference                   ║
# ╚══════════════════════════════════════╝


@dataclass(frozen=True)
class ExprInference:
    column_NullSet: Callable[[exp.Column], NullSet]
    table_column_NullSet: Callable[[exp.TableColumn], NullSet]

    def infer_nullability(self, expression: exp.Expr) -> NullSet:
        """can this expression return NULL ?"""
        match expression:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.infer_nullability(this)

            case exp.Column():
                return self.column_NullSet(expression)

            case exp.TableColumn():
                return self.table_column_NullSet(expression)

            case exp.Parameter():
                # TODO: add user annotation to permit null value
                return NullSet.NON_NULL

            case exp.Null():
                return NullSet.NULL

            case _ if is_non_null_constant(expression):
                return NullSet.NON_NULL

            case exp.Count():
                return NullSet.NON_NULL

            case _ if is_boolean_expr(expression):
                return self.infer_boolean_expr(expression).to_nullset()

            case exp.Subquery():
                return NullSet.MAYBE_NULL

            case _ if is_row(expression):
                # TODO: postgresql doc 9.2
                return NullSet.MAYBE_NULL

            case _:
                return NullSet.MAYBE_NULL

    def infer_boolean_expr(self, expression: exp.Expr) -> BooleanSet:
        """what are the possible outcomes of this boolean expression ?"""
        match expression:
            case exp.Paren(this=this):
                return self.infer_boolean_expr(this)

            case exp.And(this=left, expression=right):
                return self.infer_boolean_expr(left) & self.infer_boolean_expr(right)

            case exp.Or(this=left, expression=right):
                return self.infer_boolean_expr(left) | self.infer_boolean_expr(right)

            case exp.Not(this=this):
                return ~self.infer_boolean_expr(this)

            case exp.Expr(this=left, expression=right) if is_comparison_operator(expression):
                return _comparison_operator(
                    self.infer_nullability(left), self.infer_nullability(right)
                )

            case exp.NullSafeEQ(this=left, expression=right):
                return _is_not_distinct_from_operator(
                    self.infer_nullability(left), self.infer_nullability(right)
                )

            case exp.NullSafeNEQ(this=left, expression=right):
                return ~(
                    _is_not_distinct_from_operator(
                        self.infer_nullability(left), self.infer_nullability(right)
                    )
                )

            case exp.Is():
                return self._is_expression(expression)

            case _ if is_subquery_predicate(expression):
                return _subquery_predicate(expression)

            case exp.Boolean(this=this):
                return BooleanSet.TRUE if this else BooleanSet.FALSE

            case exp.Null():
                return BooleanSet.UNKNOWN

            case exp.Between():
                raise SimplificationError()

            case _:
                return BooleanSet.TOP

    def _is_expression(self, expression: exp.Is):
        negate = bool(expression.args.get("negate"))
        right = expression.right.unnest()
        match right:
            case exp.Boolean():
                left_booleanset = self.infer_boolean_expr(expression.left)
                right_booleanset = IS_BOOLEAN_TABLE[(negate, is_true(right))]
                if left_booleanset.value.issubset(right_booleanset.value):
                    return BooleanSet.TRUE
                if left_booleanset.value.isdisjoint(right_booleanset.value):
                    return BooleanSet.FALSE
                return BooleanSet.TRUE_OR_FALSE
            case exp.Null():
                left_NullSet = self.infer_nullability(expression.left)
                if left_NullSet is NullSet.NULL:
                    return BooleanSet.FALSE if negate else BooleanSet.TRUE
                if left_NullSet is NullSet.NON_NULL:
                    return BooleanSet.TRUE if negate else BooleanSet.FALSE
                return BooleanSet.TRUE_OR_FALSE
            case _:
                return BooleanSet.TRUE_OR_FALSE


IS_BOOLEAN_TABLE = {
    (False, True): BooleanSet.TRUE,
    (False, False): BooleanSet.FALSE,
    (True, True): BooleanSet.FALSE_OR_UNKNOWN,
    (True, False): BooleanSet.TRUE_OR_UNKNOWN,
}


def _comparison_operator(left: NullSet, right: NullSet):
    match (left, right):
        case (NullSet.NULL, _) | (_, NullSet.NULL):
            return BooleanSet.UNKNOWN
        case (NullSet.MAYBE_NULL, _) | (_, NullSet.MAYBE_NULL):
            return BooleanSet.TOP
        case (NullSet.NON_NULL, NullSet.NON_NULL):
            return BooleanSet.TRUE_OR_FALSE


def _is_not_distinct_from_operator(left: NullSet, right: NullSet):
    match (left, right):
        case (NullSet.NULL, NullSet.NULL):
            return BooleanSet.TRUE
        case (NullSet.NULL, NullSet.NON_NULL) | (NullSet.NON_NULL, NullSet.NULL):
            return BooleanSet.FALSE
        case _:
            return BooleanSet.TRUE_OR_FALSE


def _subquery_predicate(expression: exp.Any | exp.All | exp.Exists | exp.In):
    return BooleanSet.TOP


def _strict_fn():
    """
    Strict function evaluate to NULL if any argument is NULL
    """
    return BooleanSet.TOP


def _non_strict_fn(self):
    return BooleanSet.TOP
