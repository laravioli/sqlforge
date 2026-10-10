from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from sqlglot import exp

from .context import Context, Formula, Kind
from .exception import StarNotExpanded, UnknownColumn
from .expression import (
    is_boolean_expr,
    is_comparison_operator,
    is_non_null_constant,
    is_strict_binary,
)
from .relation import Key, Row, Subquery

type Predicate = tuple[Formula, Formula]


class ScopeProtocol(Protocol):
    ctx: Context
    side: list[Formula]
    notebook: dict[exp.Expr, Formula]

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...


@dataclass(frozen=True, slots=True)
class Env:
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


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env

    @property
    def ctx(self):
        return self.env.scope.ctx

    @property
    def notebook(self) -> dict[exp.Expr, Formula]:
        return self.env.scope.notebook

    def null(self, e: exp.Expr) -> Formula:
        ctx = self.ctx

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
                    transform = lambda i: self.pred(i.this)
                else:
                    transform = lambda i: self.pred(
                        exp.EQ(this=this.copy(), expression=i.this.copy())
                    )

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

            case _ if is_strict_binary(e):
                return self.null(e.this) | self.null(e.expression)

            case exp.Func():
                return self._func(e)

            case exp.Star():
                raise StarNotExpanded("* must be expanded")

            case _:
                return ctx.fresh(Kind.MAYBE)

    def pred(self, e: exp.Expr) -> Predicate:
        """
        Representation:
            True:   (1,0)
            False:  (0,1)
            Unknow: (0,0)
        """

        ctx = self.ctx

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

            case _ if is_comparison_operator(e):
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

    def _unknown(self, pred: Predicate) -> Formula:
        t, f = pred
        return ~t & ~f

    def _func(self, e: exp.Func):
        return self.ctx.fresh(Kind.MAYBE)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
