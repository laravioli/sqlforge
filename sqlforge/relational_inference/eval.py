from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol

from sqlglot import exp

from .context import Context, Formula, Kind
from .exception import StarNotExpanded, UnknownColumn
from .expressions import (
    Comparison,
    is_boolean_expr,
    is_comparison,
    is_non_null_constant,
    is_strict_binary_operator,
)
from .relation import Key, Row, Subquery

type PredicateFormula = tuple[Formula, Formula]


class ScopeProtocol(Protocol):
    ctx: Context
    side: list[Formula]
    notebook: Notebook

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...


@dataclass(frozen=True, slots=True)
class Env:
    """
    A view of current null facts of a row, at this point of evaluation
    """

    scope: ScopeProtocol
    nulls: Mapping[Key, Formula]
    outer: Env | None

    def evaluator(self):
        return Evaluator(self)

    def bind(self, *rows: Row) -> Env:
        return replace(
            self,
            nulls={k: n for row in rows for k, n in row.nulls.items()},
        )

    def extend(self, *rows: Row) -> Env:
        return replace(
            self,
            nulls={k: n for row in (self, *rows) for k, n in row.nulls.items()},
        )

    def null(self, key: Key) -> Formula:
        env: Env | None = self
        while env is not None:
            if (formula := env.nulls.get(key)) is not None:
                return formula
            env = env.outer
        raise UnknownColumn(key)

    def fields(self, alias: str) -> list[Formula]:
        env: Env | None = self
        while env is not None:
            found = [f for (a, _), f in env.nulls.items() if a == alias]
            if found:
                return found
            env = env.outer
        raise UnknownColumn((alias, "*"))


@dataclass
class Notebook:
    """
    Store reusable facts about a row, from their creation to the end of a scope\n
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

    def compare(self, op: Comparison, left: exp.Expr, right: exp.Expr) -> Formula:
        if not (self._reusable(left) and self._reusable(right)):
            return self.ctx.fresh(Kind.VALUE)
        less, equal, greater = self._order(left, right)
        match op:
            case exp.EQ():
                return equal
            case exp.NEQ():
                return ~equal
            case exp.LT():
                return less
            case exp.GT():
                return greater
            case exp.LTE():
                return ~greater
            case exp.GTE():
                return ~less

    def _order(self, left: exp.Expr, right: exp.Expr) -> tuple[Formula, Formula, Formula]:
        if left == right:
            return self.ctx.false, self.ctx.true, self.ctx.false

        first, second = sorted((left, right), key=hash)
        equal = self._var(("eq", first, second), Kind.VALUE)
        below = self._var(("lt", first, second), Kind.VALUE)
        less, greater = ~equal & below, ~equal & ~below

        return (less, equal, greater) if first == left else (greater, equal, less)

    def holds(self, tag: str, *operands: exp.Expr):
        if not all(self._reusable(o) for o in operands):
            return self.ctx.fresh(Kind.VALUE)
        return self._var((f"{tag}_h", *operands), Kind.VALUE)

    def unknown(self, tag: str, expr: exp.Expr):
        if not self._reusable(expr):
            return self.ctx.fresh(Kind.MAYBE)
        return self._var((f"{tag}_u", expr), Kind.MAYBE)

    def _reusable(self, expr: exp.Expr):
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


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env

    @property
    def ctx(self):
        return self.env.scope.ctx

    @property
    def notebook(self) -> Notebook:
        return self.env.scope.notebook

    def null(self, e: exp.Expr) -> Formula:
        ctx = self.ctx
        notebook = self.notebook

        match e:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.null(this)

            case exp.Column(table=table, name=name):
                if e.is_star:
                    raise StarNotExpanded("c.* must be expanded")
                return self.env.null((table, name))

            case exp.TableColumn():
                return ctx.fresh(Kind.MAYBE) & ctx.all(self.env.fields(e.name))

            case exp.Parameter(this=this):
                return ctx.param(this.to_py())  # type: ignore

            case exp.Null():
                return ctx.true

            case _ if is_non_null_constant(e):
                return ctx.false

            case exp.Count():
                return ctx.false

            case (
                exp.Window(this=this) | exp.Filter(this=this)
            ):  # count(*) OVER/FILTER → the aggregate decides
                return self.null(this)

            case exp.Subquery(this=this):
                return self.null(this)  # unwrap

            case exp.Select() | exp.SetOperation():  # scalar subquery
                return self._subquery(e).scalar_null

            case exp.Expr(this=head, expressions=tail) if isinstance(
                e, (exp.Coalesce, exp.Greatest, exp.Least)
            ):
                return ctx.all(self.null(expr) for expr in [head, *tail])

            case exp.Nullif(this=left, expression=right):
                l_null, r_null = self.null(left), self.null(right)
                eq = ctx.fresh(Kind.VALUE)  # NOTE: ill dot notebook later, so rework with notebook
                return l_null | (~r_null & eq)

            case exp.Case(this=this):
                if this is None:

                    def transform(i):
                        return self.pred(i.this)
                else:

                    def transform(i):
                        return self.pred(exp.EQ(this=this.copy(), expression=i.this.copy()))

                _ifs = (
                    (transform(i), self.null(i.args.get("true")))  # type: ignore
                    for i in e.args.get("ifs", [])
                )
                out, false_before = ctx.false, ctx.true

                for (t, _), value in _ifs:
                    out |= false_before & t & value
                    false_before &= ~t
                default = self.null(e.args.get("default") or exp.Null())

                return out | (false_before & default)

            case _ if is_boolean_expr(e):
                return self._unknown(self.pred(e))

            case exp.Neg(this=this) | exp.BitwiseNot(this=this):
                return self.null(this)

            case exp.Cast(this=this):
                return self.null(this)

            case exp.DPipe(this=l, expression=r):
                return ctx.fresh(Kind.MAYBE) & (self.null(l) | self.null(r))

            case _ if is_strict_binary_operator(e):
                return self.null(e.this) | self.null(e.expression)

            case exp.Func():
                return self._func(e)

            case exp.Star():
                raise StarNotExpanded("* must be expanded")

            case _:
                return ctx.fresh(Kind.MAYBE)

    def pred(self, e: exp.Expr) -> PredicateFormula:
        """
        Representation:
            True:   (1,0)
            False:  (0,1)
            Unknow: (0,0)
        """

        ctx = self.ctx
        notebook = self.notebook

        match e:
            case exp.Paren(this=this):
                return self.pred(this)

            case exp.And(this=left, expression=right):
                t_l, f_l = self.pred(left)
                t_r, f_r = self.pred(right)

                return t_l & t_r, f_l | f_r

            case exp.Or(this=left, expression=right):
                t_l, f_l = self.pred(left)
                t_r, f_r = self.pred(right)

                return t_l | t_r, f_l & f_r

            case exp.Not(this=this):
                t, f = self.pred(this)
                return f, t

            case _ if is_comparison(e):
                if a := e.find(exp.All, exp.Any):
                    sub_expr = a.find(exp.Select, exp.SetOperation)
                    assert sub_expr is not None
                    sub = self._subquery(sub_expr)
                    match a:
                        case exp.All():
                            return ctx.true, ctx.false
                        case exp.Any():
                            return ctx.true, ctx.false
                else:
                    return ctx.true, ctx.false

            case exp.Boolean(this=this):
                return (ctx.true, ctx.false) if this else (ctx.false, ctx.true)

            case exp.Null():
                return ctx.false, ctx.false

            case _:
                u, v = ctx.fresh(Kind.VALUE), ctx.fresh(Kind.VALUE)
                return u, ~u & v

    def _unknown(self, pred: PredicateFormula) -> Formula:
        t, f = pred
        return ~t & ~f

    def _func(self, e: exp.Func):
        return self.ctx.fresh(Kind.MAYBE)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
