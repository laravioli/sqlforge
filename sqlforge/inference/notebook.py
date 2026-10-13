from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp

from .context import Context, Formula, Kind
from .expressions import Comparison


@dataclass
class Notebook:
    """
    Store some reusable facts about a row, from their creation to the end of a scope\n
    If a fact is not reusable, a new var is returned instead.
    """

    ctx: Context
    functions: None  # TODO
    _vars: dict[tuple[str, *tuple[exp.Expr, ...]], Formula] = field(default_factory=dict)
    _reusables: dict[exp.Expr, bool] = field(default_factory=dict)

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

    def _order(self, left: exp.Expr, right: exp.Expr) -> tuple[Formula, Formula, Formula]:
        if left == right:
            return self.ctx.false, self.ctx.true, self.ctx.false

        first, second = sorted((left, right), key=hash)
        equal = self._var(("eq", first, second), Kind.TRUTH)
        below = self._var(("lt", first, second), Kind.TRUTH)
        less, greater = ~equal & below, ~equal & ~below
        return (less, equal, greater) if first == left else (greater, equal, less)

    def holds(self, tag: str, *operands: exp.Expr):
        """
        boolean fact
        """
        if not all(self._reusable(o) for o in operands):
            return self.ctx.fresh(Kind.TRUTH)
        return self._var((f"{tag}_h", *operands), Kind.TRUTH)

    def null(self, tag: str, expr: exp.Expr):
        """
        null fact
        """
        if not self._reusable(expr):
            return self.ctx.fresh(Kind.MAYBE)
        return self._var((f"{tag}_n", expr), Kind.MAYBE)

    def _reusable(self, expr: exp.Expr):
        """whitelist that allow storing a fact"""
        reusable = self._reusables.get(expr)
        if reusable is None:
            reusable = not (bool(expr.find(exp.Query)) or self._volatile(expr))
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
