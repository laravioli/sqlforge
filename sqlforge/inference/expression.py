from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, TypeIs

from sqlglot import exp
from sqlglot.optimizer.simplify import extract_date

from .enums import Nullability, SqlBool, lift1, lift2

# NOTE: expression below are part of select list OR predicate clause
# NOTE: they are evaluated column wise

# NOTE: current heuristic:
# NOTE: 1. assume that evaluated expression are already simplified by sqlglot
# NOTE:    which mean the code doesnt handle some case precisely like boolean constant expression, ex: false < true
# NOTE: 2. we don't perform expression equality check simplification because of non-deterministic function, ex: now() is distinct from now()

# 1. Schema NULL / NOT NULL
# 2. JOIN-induced nullability
# 3. NULL literals
# 4. IS NULL / IS NOT NULL
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

BOOLEAN_EXPRESSION = (exp.Predicate, exp.Connector, exp.Boolean)

LOGICAL_EXPRESSION = (exp.And, exp.Or, exp.Not)
type Logical = exp.And | exp.Or | exp.Not

DISTINCT_FROM_COMPARISON = (exp.NullSafeNEQ, exp.NullSafeEQ)

COMPARISON = (*DISTINCT_FROM_COMPARISON, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Is)
type Comparison = (
    exp.NullSafeNEQ
    | exp.NullSafeEQ
    | exp.EQ
    | exp.NEQ
    | exp.GT
    | exp.GTE
    | exp.LT
    | exp.LTE
    | exp.Is
)

SUBQUERY_PREDICATE = (exp.Any, exp.All, exp.Exists, exp.In)
type SubqueryPredicate = exp.Any | exp.All | exp.Exists | exp.In

NULL_PROPAGATING_UNARY_FUNC = (exp.Upper, exp.Lower, exp.Length, exp.Trim)
NULL_PROPAGATING_BINARY_FUNC = (exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.DPipe)


def is_non_null_constant(expression: exp.Expr) -> bool:
    expression = expression.this if isinstance(expression, exp.Neg) else expression
    return isinstance(expression, NON_NULL_CONSTANT) or extract_date(expression) is not None


def is_parameter(expression: exp.Expr) -> TypeIs[exp.Parameter]:
    return isinstance(expression, exp.Parameter)


def is_boolean(expression: exp.Expr):
    return isinstance(expression, BOOLEAN_EXPRESSION)


def is_logical(expression: exp.Expr) -> TypeIs[Logical]:
    return isinstance(expression, LOGICAL_EXPRESSION)


def is_comparison(
    expression: exp.Expr,
) -> TypeIs[Comparison]:
    return isinstance(expression, COMPARISON)


def is_disctinct_from_comparison(
    expression: exp.Expr,
) -> TypeIs[exp.NullSafeNEQ | exp.NullSafeEQ]:
    return isinstance(expression, DISTINCT_FROM_COMPARISON)


def is_subquery_predicate(expression: exp.Expr) -> TypeIs[SubqueryPredicate]:
    return isinstance(expression, SUBQUERY_PREDICATE)


def is_true(expression: exp.Expr) -> bool:
    return type(expression) is exp.Boolean and expression.this


def is_null(expression: exp.Expr) -> TypeIs[exp.Null]:
    return type(expression) is exp.Null


def is_row(expression: exp.Expr) -> bool:
    return isinstance(expression, exp.Anonymous) and expression.this == "row"


# ╔══════════════════════════════════════╗
# ║          Boolean lattice             ║
# ╚══════════════════════════════════════╝


# Lattice
_TOP = frozenset(SqlBool)
_TRUE_OR_FALSE = frozenset({SqlBool.TRUE, SqlBool.FALSE})
_TRUE_OR_UNKNOWN = frozenset({SqlBool.TRUE, SqlBool.UNKNOWN})
_FALSE_OR_UNKNOWN = frozenset({SqlBool.FALSE, SqlBool.UNKNOWN})
_TRUE = frozenset({SqlBool.TRUE})
_FALSE = frozenset({SqlBool.FALSE})
_UNKNOWN = frozenset({SqlBool.UNKNOWN})


def cast_to_null_lattice(lattice: frozenset[SqlBool]) -> Nullability:
    if lattice == _UNKNOWN:
        return Nullability.NULL
    if _UNKNOWN in lattice:
        return Nullability.MAYBE_NULL
    return Nullability.NON_NULL


# ╔══════════════════════════════════════╗
# ║          Inference                   ║
# ╚══════════════════════════════════════╝


@dataclass(frozen=True)
class ExprInference:
    column_nullability: Callable[[exp.Column], Nullability]

    DISTINCT_FROM_MAP: ClassVar = {
        (Nullability.NULL, Nullability.NULL): _TRUE,
        (Nullability.NULL, Nullability.NON_NULL): _FALSE,
        (Nullability.NON_NULL, Nullability.NULL): _FALSE,
    }
    IS_BOOLEAN_MAP: ClassVar = {
        (False, True): _TRUE,
        (False, False): _FALSE,
        (True, True): _FALSE_OR_UNKNOWN,
        (True, False): _TRUE_OR_UNKNOWN,
    }

    def infer_nullability(self, expression: exp.Expr) -> Nullability:
        """can this expression return NULL ?"""
        match expression:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.infer_nullability(this)

            case exp.Column():
                return self.column_nullability(expression)

            case exp.Null():
                return Nullability.NULL

            case _ if is_non_null_constant(expression):
                return Nullability.NON_NULL

            case _ if is_boolean(expression):
                return cast_to_null_lattice(self.infer_boolean_expression(expression))

            case exp.Subquery():
                return Nullability.MAYBE_NULL

            case _ if is_row(expression):
                return Nullability.MAYBE_NULL

            case _:
                return Nullability.MAYBE_NULL

    def infer_boolean_expression(self, expression: exp.Expr) -> frozenset[SqlBool]:
        """what are the possible outcomes of this boolean expression ?"""
        match expression:
            case exp.Paren(this=this):
                return self.infer_boolean_expression(this)

            case _ if is_logical(expression):
                return self._logical(expression)

            case _ if is_comparison(expression):
                return self._comparison(expression)

            case _ if is_subquery_predicate(expression):
                return self._subquery_predicate(expression)

            case exp.Boolean(this=this):
                return _TRUE if this else _FALSE

            case exp.Null():
                return _UNKNOWN

            case exp.Between():
                raise SimplificationError()

            case _:
                return _TOP

    def _logical(self, expression: exp.And | exp.Or | exp.Not):
        # we don't deduce things like A = P or NOT (A = P)
        match expression:
            case exp.And(this=left, expression=right):
                return lift2(
                    SqlBool.__and__,
                    self.infer_boolean_expression(left),
                    self.infer_boolean_expression(right),
                )
            case exp.Or(this=left, expression=right):
                return lift2(
                    SqlBool.__or__,
                    self.infer_boolean_expression(left),
                    self.infer_boolean_expression(right),
                )
            case exp.Not(this=this):
                return lift1(SqlBool.__invert__, self.infer_boolean_expression(this))

    def _comparison(self, expression: Comparison) -> frozenset[SqlBool]:

        if isinstance(expression, exp.Is):
            return self._is_expression(expression)

        left = self.infer_nullability(expression.left)
        right = self.infer_nullability(expression.right)

        if is_disctinct_from_comparison(expression):
            return self._distinct_from_expression(expression, left, right)

        match (left, right):
            case (Nullability.NULL, _) | (_, Nullability.NULL):
                lattice = _UNKNOWN
            case (Nullability.MAYBE_NULL, _) | (_, Nullability.MAYBE_NULL):
                lattice = _TOP
            case (Nullability.NON_NULL, Nullability.NON_NULL):
                # we don't infer constant expression (which would narrow to _TRUE or _FALSE)
                lattice = _TRUE_OR_FALSE

        return lattice

    def _distinct_from_expression(
        self, expression: exp.NullSafeEQ | exp.NullSafeNEQ, left: Nullability, right: Nullability
    ):
        bool_lattice = self.DISTINCT_FROM_MAP.get((left, right), _TRUE_OR_FALSE)

        if isinstance(expression, exp.NullSafeNEQ) and bool_lattice is not _TRUE_OR_FALSE:
            bool_lattice = _FALSE if bool_lattice is _TRUE else _TRUE

        return bool_lattice

    def _is_expression(self, expression: exp.Is):
        negate = bool(expression.args.get("negate"))
        right = expression.right.unnest()
        match right:
            case exp.Boolean():
                left_lattice = self.infer_boolean_expression(expression.left)
                right_lattice = self.IS_BOOLEAN_MAP[(negate, is_true(right))]
                if left_lattice.issubset(right_lattice):
                    return _TRUE
                if left_lattice.isdisjoint(right_lattice):
                    return _FALSE
                return _TRUE_OR_FALSE
            case exp.Null():
                left_nullability = self.infer_nullability(expression.left)
                if left_nullability is Nullability.NULL:
                    return _FALSE if negate else _TRUE
                if left_nullability is Nullability.NON_NULL:
                    return _TRUE if negate else _FALSE
                return _TRUE_OR_FALSE
            case _:
                return _TRUE_OR_FALSE

    def _subquery_predicate(self, expression: SubqueryPredicate):
        return _TOP
