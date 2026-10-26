from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlglot import exp

from sqlforge.inference.context import Context, Formula, Kind

from .syntax import Comparison

# holds
ALL_NULL = "all_null"
ALL_SET = "all_set"
PRED = "pred"

type HoldFact = Literal["all_null", "all_set", "pred"]

# null
CONCAT = "||"
DOTTED_FIELD = "dot_field"
UNKNOWN = "unknown"

type NullFact = Literal["||", "dot_field", "unknown"]

# compare
_EQ = "eq"
_LT = "lt"


@dataclass
class Notebook:
    """
    Store some reusable facts about a row, from their creation to the end of a scope\n
    If a fact is not reusable, a new var is returned instead.
    """

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.functions = None
        self._vars: dict[tuple[str, *tuple[exp.Expr, ...]], Formula] = {}
        self._reusables: dict[exp.Expr, bool] = {}

    def _var(self, fact: tuple[str, *tuple[exp.Expr, ...]], kind: Kind) -> Formula:
        var = self._vars.get(fact)
        if var is None:
            var = self._vars[fact] = self.ctx.fresh(kind)
        return var

    def compare(
        self,
        op: type[Comparison],
        left: exp.Expr,
        right: exp.Expr,
    ) -> Formula:
        """
        comparison fact
        """
        if not (self._reusable(left) and self._reusable(right)):
            return self.ctx.fresh(Kind.TRUTH)
        less, equal, greater = self._order(left, right)
        match op:
            case exp.EQ:
                return equal
            case exp.NEQ:
                return ~equal
            case exp.LT:
                return less
            case exp.GT:
                return greater
            case exp.LTE:
                return ~greater
            case exp.GTE:
                return ~less
            case _:
                assert False

    def _order(
        self, left: exp.Expr, right: exp.Expr
    ) -> tuple[Formula, Formula, Formula]:
        if left == right:
            return self.ctx.false, self.ctx.true, self.ctx.false

        first, second = sorted((left, right), key=hash)
        equal = self._var((_EQ, first, second), Kind.TRUTH)
        below = self._var((_LT, first, second), Kind.TRUTH)
        less, greater = ~equal & below, ~equal & ~below
        return (less, equal, greater) if first == left else (greater, equal, less)

    def holds(self, tag: HoldFact, *operands: exp.Expr):
        """
        2-valued boolean fact
        """
        if not all(self._reusable(o) for o in operands):
            return self.ctx.fresh(Kind.TRUTH)
        return self._var((tag, *operands), Kind.TRUTH)

    def null(self, tag: NullFact, expr: exp.Expr):
        """
        null fact
        """
        if not self._reusable(expr):
            return self.ctx.fresh(Kind.MAYBE)
        return self._var((tag, expr), Kind.MAYBE)

    def _reusable(self, expr: exp.Expr):
        """whitelist that allow storing a fact"""
        reusable = self._reusables.get(expr)
        if reusable is None:
            reusable = not (bool(expr.find(exp.Query)) or self._volatile(expr))
            self._reusables[expr] = reusable
        return reusable

    def _volatile(self, expr: exp.Expr):
        if self.functions is None:
            test = lambda e: isinstance(e, (exp.Anonymous, exp.Rand, exp.Uuid))
        else:
            test = lambda e: True  # TODO

        for fn in expr.find_all(exp.Func):
            if test(fn):
                return True
        return False
