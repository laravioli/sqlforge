# The goal is to be sound by using local over-approximation
# See Static Program Analysis by Møller and Schwartzbach
# Abstract Interpretation
from __future__ import annotations

from collections.abc import Callable

from sqlglot import exp

from .exception import SimplificationError, StarNotExpanded
from .lattice import BooleanSet, CardSet, NullSet
from .structures import Output, meta_get_output
from .utils import *


class ExprInference:
    """
    Define how lattice value are transformed for each sql operator or function.\n
    Context from a current inference is injected discretly, in order to focus on semantics
    """

    def __init__(self, infer_column: Callable[[str, str | None], NullSet]):
        self._infer_column = infer_column

    def infer_nullability(self, expression: exp.Expr) -> NullSet:
        """can this expression return NULL ?"""
        match expression:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.infer_nullability(this)

            case exp.Column(table=table, name=column):
                if expression.is_star:
                    raise StarNotExpanded()
                return self._infer_column(table, column)

            case exp.TableColumn(name=table):
                return self._infer_column(table, None)

            case exp.Parameter():
                # TODO: add user annotation to permit null value
                return NullSet.NON_NULL

            case exp.Null():
                return NullSet.NULL

            case _ if is_non_null_constant(expression):
                return NullSet.NON_NULL

            case exp.Count():
                return NullSet.NON_NULL

            case exp.Subquery(this=this):
                return self.infer_nullability(this)

            case exp.Select() | exp.SetOperation():
                # scalar subqueries
                output = meta_get_output(expression)
                if output.card is CardSet.EMPTY:
                    return NullSet.NULL
                result = output.get(0)
                return result if output.card is CardSet.NON_EMPTY else result | NullSet.NULL

            case _ if is_boolean_expr(expression):
                return self.infer_boolean(expression).to_nullset()

            case exp.Coalesce(this=head, expressions=tail):
                return self._infer_coalesce([head, *tail])

            case exp.Greatest(this=head, expressions=tail) | exp.Least(this=head, expressions=tail):
                return self._infer_greatest_least([head, *tail])

            case _ if is_row(expression):
                # TODO: postgresql doc 9.2
                return NullSet.MAYBE_NULL

            case exp.Star():
                raise StarNotExpanded()

            case exp.Binary(left=left, right=right):
                return self.infer_nullability(left) | self.infer_nullability(right)

            case _:
                return NullSet.MAYBE_NULL

    # Conditional expressions

    def _infer_coalesce(self, expressions: list[exp.Expr]) -> NullSet:
        result = NullSet.NULL
        for e in expressions:
            match self.infer_nullability(e):
                case NullSet.NON_NULL:
                    return NullSet.NON_NULL
                case NullSet.MAYBE_NULL:
                    result = NullSet.MAYBE_NULL
        return result

    def _infer_greatest_least(self, expressions: list[exp.Expr]) -> NullSet:
        nulls = [self.infer_nullability(e) for e in expressions]
        if any(n is NullSet.NON_NULL for n in nulls):
            return NullSet.NON_NULL
        elif all(n is NullSet.NULL for n in nulls):
            return NullSet.NULL
        else:
            return NullSet.MAYBE_NULL

    # Boolean expressions

    def infer_boolean(self, expression: exp.Expr) -> BooleanSet:
        """what are the possible outcomes of this boolean expression ?"""
        match expression:
            case exp.Paren(this=this):
                return self.infer_boolean(this)

            case exp.And(this=left, expression=right):
                return self.infer_boolean(left).logical_and(self.infer_boolean(right))

            case exp.Or(this=left, expression=right):
                return self.infer_boolean(left).logical_or(self.infer_boolean(right))

            case exp.Not(this=this):
                return ~self.infer_boolean(this)

            case exp.Expr(this=left, expression=right) if is_comparison_operator(expression):
                if subquery_predicate := expression.find(exp.All, exp.Any):
                    subquery_output = _get_subquery_output(subquery_predicate)
                    match subquery_predicate:
                        case exp.All():
                            return self._infer_all(subquery_output, expression)
                        case exp.Any():
                            return self._infer_any(subquery_output, expression)

                return _infer_comparison_operator(
                    self.infer_nullability(left), self.infer_nullability(right)
                )

            case exp.Exists():
                return self._infer_exists(_get_subquery_output(expression))

            case exp.In(this=left):
                return self._infer_any(_get_subquery_output(expression), operator=exp.EQ(this=left))

            case exp.NullSafeEQ(this=left, expression=right):
                return _infer_distinct_operator(
                    self.infer_nullability(left), self.infer_nullability(right)
                )

            case exp.NullSafeNEQ(this=left, expression=right):
                return ~(
                    _infer_distinct_operator(
                        self.infer_nullability(left), self.infer_nullability(right)
                    )
                )

            case exp.Is():
                return self._infer_is(expression)

            case exp.Boolean(this=this):
                return BooleanSet.TRUE if this else BooleanSet.FALSE

            case exp.Null():
                return BooleanSet.UNKNOWN

            case exp.Between():
                raise SimplificationError()

            case _:
                return BooleanSet.TOP

    def _infer_is(self, expression: exp.Is) -> BooleanSet:
        negate = bool(expression.args.get("negate"))
        right = expression.right.unnest()
        match right:
            case exp.Boolean():
                left_booleanset = self.infer_boolean(expression.left)
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

    # Subquery expressions

    def _infer_all(self, subquery_output: Output, operator: Comparison) -> BooleanSet:
        if subquery_output.card is CardSet.EMPTY:
            return BooleanSet.TRUE

        result = _infer_comparison_operator(
            self.infer_nullability(operator.left), subquery_output.get(0)
        )
        match subquery_output.card:
            case CardSet.NON_EMPTY:
                return result
            case CardSet.TOP:
                return result | BooleanSet.TRUE

    def _infer_any(self, subquery_output: Output, operator: Comparison) -> BooleanSet:
        if subquery_output.card is CardSet.EMPTY:
            return BooleanSet.FALSE

        result = _infer_comparison_operator(
            self.infer_nullability(operator.left), subquery_output.get(0)
        )
        return result if subquery_output.card is CardSet.NON_EMPTY else result | BooleanSet.FALSE

    def _infer_exists(self, subquery_output: Output):
        match subquery_output.card:
            case CardSet.TOP:
                return BooleanSet.TRUE_OR_FALSE
            case CardSet.NON_EMPTY:
                return BooleanSet.TRUE
            case CardSet.EMPTY:
                return BooleanSet.FALSE


def _get_subquery_output(expression: exp.SubqueryPredicate | exp.In):
    subquery = expression.find(exp.Select, exp.SetOperation)
    assert subquery is not None
    return meta_get_output(subquery)


IS_BOOLEAN_TABLE = {
    (False, True): BooleanSet.TRUE,
    (False, False): BooleanSet.FALSE,
    (True, True): BooleanSet.FALSE_OR_UNKNOWN,
    (True, False): BooleanSet.TRUE_OR_UNKNOWN,
}


def _infer_comparison_operator(left: NullSet, right: NullSet):
    match (left, right):
        case (NullSet.NULL, _) | (_, NullSet.NULL):
            return BooleanSet.UNKNOWN
        case (NullSet.MAYBE_NULL, _) | (_, NullSet.MAYBE_NULL):
            return BooleanSet.TOP
        case (NullSet.NON_NULL, NullSet.NON_NULL):
            return BooleanSet.TRUE_OR_FALSE


def _infer_distinct_operator(left: NullSet, right: NullSet):
    match (left, right):
        case (NullSet.NULL, NullSet.NULL):
            return BooleanSet.TRUE
        case (NullSet.NULL, NullSet.NON_NULL) | (NullSet.NON_NULL, NullSet.NULL):
            return BooleanSet.FALSE
        case _:
            return BooleanSet.TRUE_OR_FALSE


def _infer_subquery_predicate(expression: exp.Any | exp.All | exp.Exists | exp.In):
    return BooleanSet.TOP


def _strict_fn():
    """
    Strict function evaluate to NULL if any argument is NULL
    """
    return BooleanSet.TOP


def _non_strict_fn(self):
    return BooleanSet.TOP
