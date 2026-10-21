from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlglot import exp

from sqlforge.inference.catalog import Composite
from sqlforge.inference.context import Formula, Kind
from sqlforge.inference.exception import StarNotExpanded
from sqlforge.inference.relation import Item, Subquery

from .notebook import Notebook
from .structures import Opaque, Pred, Scalar, Tuple, Value
from .syntax import (
    Comparison,
    is_boolean_expr,
    is_comparison,
    is_non_null_constant,
    is_row,
    is_scalar,
    is_strict_binary_operator,
    quantifier,
)
from .type_evaluator import TypeEvaluator

if TYPE_CHECKING:
    from .env import Env


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env
    types: TypeEvaluator

    @property
    def ctx(self):
        return self.env.scope.ctx

    @property
    def notebook(self) -> Notebook:
        return self.env.scope.notebook

    def type_of(self, e: exp.Expr):
        return self.types.type(e)

    def null(self, e: exp.Expr) -> Formula:
        ctx = self.ctx

        match e:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.null(this)

            case exp.Column(table=table, name=name):
                if e.is_star:
                    raise StarNotExpanded("c.* must be expanded")
                return self.env.null_of((table, name))

            case exp.TableColumn():
                return self.env.null(e.name)

            # NOTE: function will also use Dot
            case exp.Dot(this=exp.TableColumn() as row, expression=field):  # (t).f is t.f
                return self.env.null_of((row.name, field.name))

            case exp.Dot(this=base):  # (composite).f
                value = self._value(base)
                match value:
                    case Opaque():
                        return value.field_null(self.notebook.null("field", e))
                    case _:
                        raise ValueError(f"{base} can't be dotted")

            case exp.Parameter(this=this):
                return ctx.param(this.to_py())  # type: ignore

            case exp.Null():
                return ctx.true

            case _ if is_non_null_constant(e) or is_row(e):
                return ctx.false

            case exp.Count():
                return ctx.false

            case exp.Subquery(this=this):
                return self.null(this)  # unwrap

            case exp.Select() | exp.SetOperation():  # scalar subquery
                return self._subquery(e).scalar_null

            case exp.Expr(this=head, expressions=tail) if isinstance(
                e, (exp.Coalesce, exp.Greatest, exp.Least)
            ):
                return ctx.all(self.null(expr) for expr in [head, *tail])

            case exp.Nullif(this=left, expression=right):
                l, r = self._value(left), self._value(right)
                return l.null | self._compare_values(exp.EQ, l, r, left, right).t

            case exp.Case():
                return ctx.any(taken & self.null(r) for taken, r in self._case(e))

            case _ if is_boolean_expr(e):
                return self.pred(e).as_null

            case exp.Neg(this=this) | exp.BitwiseNot(this=this):
                return self.null(this)

            case exp.Cast(this=this):
                return self.null(this)

            case exp.DPipe(this=l, expression=r):
                return self.notebook.null("||", e) & (self.null(l) | self.null(r))

            case _ if is_strict_binary_operator(e):
                return self.null(e.this) | self.null(e.expression)

            case exp.Star():
                raise StarNotExpanded("* must be expanded")

            # this block should stay here
            case exp.Func():
                return self._func(e)

            case _:
                return ctx.fresh(Kind.MAYBE)

    def pred(self, e: exp.Expr) -> Pred:
        ctx = self.ctx
        match e:
            case exp.Paren(this=this):
                return self.pred(this)

            case exp.And(this=l, expression=r):
                return self.pred(l) & self.pred(r)

            case exp.Or(this=l, expression=r):
                return self.pred(l) | self.pred(r)

            case exp.Not(this=this):
                return ~self.pred(this)

            case exp.Null():
                return Pred(ctx.false, ctx.false)

            case exp.Boolean(this=truth):
                p = Pred.of(holds=ctx.true)
                return p if truth else ~p

            case exp.Is():
                return self._is(e)

            case exp.Expr(left=l, right=r) if is_comparison(e):
                if (q := quantifier(r)) is not None:
                    return self._quantified(type(e), l, *q)
                else:
                    return self._compare(type(e), self._value(l), self._value(r), l, r)

            case exp.NullSafeEQ(left=l, right=r):
                return Pred.of(holds=self._not_distinct(l, r))

            case exp.NullSafeNEQ(left=l, right=r):
                return ~Pred.of(holds=self._not_distinct(l, r))

            case exp.In():
                return self._in(e)

            case exp.Exists(this=query):
                sub = self._subquery(query.unnest())
                return Pred.of(holds=~sub.empty)

            case exp.Case():
                paths = [(taken, self.pred(r)) for taken, r in self._case(e)]
                return Pred(
                    ctx.any(taken & t for taken, (t, _) in paths),
                    ctx.any(taken & f for taken, (_, f) in paths),
                )

            case exp.Coalesce():
                return self._coalesce([e.this, *e.expressions])

            case exp.Between():
                return self._between(e)

            case _:
                known = (
                    ~self.notebook.null("pred", e)  # self.null(e) would call back into self.pred(e)
                    if is_boolean_expr(e)
                    else ~self.null(e)
                )
                return Pred.of(holds=self.notebook.holds("pred", e), known=known)

    def _all(self, ps: Sequence[Pred]):
        return Pred(self.ctx.all(p.t for p in ps), self.ctx.any(p.f for p in ps))

    def _any(self, ps: Sequence[Pred]):
        return Pred(self.ctx.any(p.t for p in ps), self.ctx.all(p.f for p in ps))

    def _value(self, e: exp.Expr) -> Value:
        """
        evaluate expression nullability and build a value
        """
        e = e.unnest()
        match e:
            case exp.TableColumn(name=alias):
                return self.env.item(alias)

            case x if is_row(x):
                return Tuple(self.ctx.false, x.expressions, self.null)

            case x if is_scalar(x):
                return Scalar(self.null(x))

            case x:
                shape = self.types.shape(x)
                match shape:
                    case "scalar":
                        return Scalar(self.null(x))
                    case Composite(fields=()):
                        all_non_null = all_null = self.ctx.true
                    case Composite():
                        all_non_null = self.notebook.holds("all_non_null", x)
                        all_null = ~all_non_null & self.notebook.holds("all_null", x)
                    case "unknown":
                        all_non_null = self.notebook.holds("all_non_null", x)
                        all_null = self.notebook.holds("all_null", x)

                return Opaque(self.null(x), all_null, all_non_null, shape)

    def _compare(
        self, op: type[Comparison], l: Value, r: Value, left: exp.Expr, right: exp.Expr
    ) -> Pred:
        """
        `left op right` as written (9.25.5): ROW(...) op ROW(...) compares field by field,
        anything else compares as values (9.25.6). A cast row is not a Tuple, so it compares as a value.
        (IN lists and subqueries use the other rule, see _row_constructor.)
        """
        if isinstance(l, Tuple) and isinstance(r, Tuple):
            return self._row_compare(op, l, r)
        return self._compare_values(op, l, r, left, right)

    def _compare_values(
        self, op: type[Comparison], l: Value, r: Value, left: exp.Expr, right: exp.Expr
    ) -> Pred:
        """
        comparison of values (9.25.6): NULL if either whole value is NULL; composites compare
        with record_eq / record_lt, where NULL fields compare equal.
        Operands are already evaluated, so callers evaluate each one once.
        """
        if op in (exp.EQ, exp.NEQ):
            eq = self._equal(l, r, left, right)
            holds = eq if op is exp.EQ else ~eq
        else:
            holds = self.notebook.compare(op, left, right)
        return Pred.of(holds=holds, known=~l.null & ~r.null)

    def _equal(self, l, r, left: exp.Expr, right: exp.Expr) -> Formula:
        """equality of two non-NULL values; NULL fields compare equal"""
        match l, r:
            case Tuple(keys=lk), Tuple(keys=rk):
                # from _not_distinct, and rows compared as values (nested rows, ARRAY elements)
                return self.ctx.all(self._not_distinct(x, y) for x, y in zip(lk, rk, strict=True))
            case Tuple() | Item(), Tuple() | Item():
                return self.ctx.all(
                    self._same_null(x, y, self.notebook.holds(f"field_eq:{i}", left, right))
                    for i, (x, y) in enumerate(zip(l.fields, r.fields, strict=True))
                )
            case _:
                return self.notebook.compare(exp.EQ, left, right)

    def _row_compare(
        self, op: type[Comparison], l: Tuple, r: Tuple, lv: Sequence[Value] | None = None
    ) -> Pred:
        """
        ROW(...) op ROW(...) (9.25.5): = holds if every pair is equal, fails if one pair differs;
        <> dually; <, <=, >, >= are decided by the first pair that is unequal or NULL.
        Pairs compare as values (a nested row is a composite value).
        lv: the left fields already evaluated (an IN list compares one left row to several)
        """
        ctx = self.ctx
        lv = [self._value(k) for k in l.keys] if lv is None else lv
        rv = [self._value(k) for k in r.keys]
        pairs = list(zip(lv, rv, l.keys, r.keys, strict=True))
        eq = [self._compare_values(exp.EQ, a, b, x, y) for a, b, x, y in pairs]

        match op:
            case exp.EQ:
                return self._all(eq)
            case exp.NEQ:
                return ~self._all(eq)

        strict = exp.LT if op in (exp.LT, exp.LTE) else exp.GT
        true = false = ctx.false
        equal_so_far = ctx.true
        for (a, b, x, y), (eq_t, eq_f) in zip(pairs, eq):
            holds, fails = self._compare_values(strict, a, b, x, y)
            true |= equal_so_far & eq_f & holds
            false |= equal_so_far & eq_f & fails
            equal_so_far &= eq_t
        if op in (exp.LTE, exp.GTE):
            true |= equal_so_far
        else:
            false |= equal_so_far
        return Pred(true, false)

    def _not_distinct(self, left, right) -> Formula:
        l, r = self._value(left), self._value(right)
        return self._same_null(l.null, r.null, self._equal(l, r, left, right))

    def _same_null(self, l_null: Formula, r_null: Formula, equal: Formula) -> Formula:
        return (l_null & r_null) | (~l_null & ~r_null & equal)

    def _quantified(
        self,
        op: type[Comparison],
        left: exp.Expr,
        quantifier: Literal["any", "all"],
        inner: exp.Expr,
    ) -> Pred:
        """
        left op ANY | ALL (array | subquery), SOME is ANY (9.24.3-4, 9.25.3-4).
        - ARRAY[...] is expanded, one comparison per element; rows compare as composite values.
        - a subquery is summarized (_summarized); a ROW(...) on the left compares field by field.
        - any other array (column, parameter, function, ARRAY(SELECT ...)) is summarized too,
          and a NULL array gives NULL.
        """
        ctx = self.ctx
        inner = inner.unnest()
        match inner:
            case exp.Array(expressions=items) if not any(
                isinstance(i, (exp.Query, exp.Array)) for i in items
            ):
                l = self._value(left)
                preds = [self._compare_values(op, l, self._value(i), left, i) for i in items]
                return self._any(preds) if quantifier == "any" else self._all(preds)

            case exp.Subquery() | exp.Select() | exp.SetOperation():
                while isinstance(inner, exp.Subquery):
                    inner = inner.this
                sub = self._subquery(inner)  # type: ignore[arg-type]
                can_null = any(ctx.sat(sub.relation.invariant & n) for n in sub.nulls)
                if (row := self._row_constructor(left)) is not None:
                    lnulls = self._value(row).fields  # type: ignore[union-attr]
                else:
                    lnulls = [self._value(left).null]
                return self._summarized(op, quantifier, lnulls, sub.empty, can_null)

            case _:  # an array value
                t, f = self._summarized(
                    op, quantifier, [self._value(left).null], ctx.fresh(Kind.EMPTY), True
                )
                array_null = ctx.false if isinstance(inner, exp.Array) else self.null(inner)
                return Pred(~array_null & t, ~array_null & f)

    def _summarized(
        self,
        op: type[Comparison],
        quantifier: Literal["any", "all"],
        lnulls: Sequence[Formula],
        empty: Formula,
        can_null: bool,
    ) -> Pred:
        """
        ANY / ALL over elements (or subquery rows) we can't see one by one. Each comparison is
        true, false or NULL; which one stays open (fresh atoms) but its NULL-ness is exact:
        - it can be true or false only if the left fields it needs are set: all of them for =
          to hold, one for = to fail (dually for <>), the first one for <, <=, >, >=
        - it can be NULL only if a left field or an element can be NULL (can_null).
        ANY is true if some comparison is true, false if all are false or there is no element.
        ALL is false if some comparison is false, true if all are true or there is no element.
        """
        ctx = self.ctx
        all_set = ctx.all(~n for n in lnulls)
        any_set = ctx.any(~n for n in lnulls)
        match op:
            case exp.EQ:
                can_true, can_false = all_set, any_set
            case exp.NEQ:
                can_true, can_false = any_set, all_set
            case _:
                can_true = can_false = ~lnulls[0] if lnulls else ctx.true
        never_null = all_set & (ctx.false if can_null else ctx.true)
        some_true, some_false = ctx.fresh(Kind.TRUTH), ctx.fresh(Kind.TRUTH)

        if quantifier == "any":
            true = ~empty & can_true & some_true
            false = empty | (~some_true & can_false & (never_null | some_false))
        else:
            false = ~empty & can_false & some_false
            true = empty | (~some_false & can_true & (never_null | some_true))
        return Pred(true, false)

    def _in(self, e: exp.In) -> Pred:
        """
        x IN (a, b) is x = a OR x = b; x IN (subquery) is x = ANY (subquery) (9.24.2, 9.25.1).
        Unlike `=`, an IN list sees a cast row as a row constructor:
        ROW(1, NULL)::pair IN (ROW(1, NULL)::pair) compares field by field (NULL), not as values.
        """
        ctx, left = self.ctx, e.this
        if (query := e.args.get("query")) is not None:
            return self._quantified(exp.EQ, left, "any", query)
        if not e.expressions:  # IN UNNEST(...) and other non-Postgres forms
            return Pred.fresh(ctx)

        if (lrow := self._row_constructor(left)) is not None:
            l = self._value(lrow)
            assert isinstance(l, Tuple)
            lv = [self._value(k) for k in l.keys]
            preds = []
            for item in e.expressions:
                if (rrow := self._row_constructor(item)) is None:
                    preds.append(Pred.fresh(ctx))  # Postgres rejects a non-row in a row IN
                else:
                    preds.append(self._row_compare(exp.EQ, l, self._value(rrow), lv))  # type: ignore[arg-type]
        else:
            # left is not a row constructor even under casts, so it can't be a Tuple
            l = self._value(left)
            preds = [
                self._compare_values(exp.EQ, l, self._value(i), left, i) for i in e.expressions
            ]

        return self._any(preds)

    def _row_constructor(self, e: exp.Expr) -> exp.Expr | None:
        """ROW(...), possibly under casts: what Postgres resolves to a row constructor"""
        e = e.unnest()
        while isinstance(e, exp.Cast):
            e = e.this.unnest()
        return e if is_row(e) else None

    def _is(self, e: exp.Is) -> Pred:
        left, right, negate = e.this, e.expression, bool(e.args.get("negate"))

        match right:
            case exp.Null():
                match self._value(left):
                    case Item(null=null, fields=fields) | Tuple(null=null, fields=fields):
                        return (
                            Pred.of(holds=null | self.ctx.all(fields))
                            if not negate
                            else Pred.of(holds=~null & self.ctx.all(~f for f in fields))
                        )

                    case Scalar(null=null):
                        p = Pred.of(holds=null)
                        return p if not negate else ~p

                    case Opaque(null=null, all_null=all_null, all_non_null=all_non_null):
                        true = ~null & all_non_null if negate else null | all_null
                        return Pred.of(holds=true)

            case exp.Boolean(this=truth):
                t, f = self.pred(left)
                p = Pred.of(holds=t if truth else f)
                return ~p if negate else p

            case _:
                return Pred.fresh(self.ctx)

    def _between(self, e: exp.Between) -> Pred:
        x, low, high = e.this, e.args["low"], e.args["high"]
        xv, lv, hv = self._value(x), self._value(low), self._value(high)  # each evaluated once
        p = self._compare(exp.GTE, xv, lv, x, low) & self._compare(exp.LTE, xv, hv, x, high)
        if e.args.get("symmetric"):
            p |= self._compare(exp.GTE, xv, hv, x, high) & self._compare(exp.LTE, xv, lv, x, low)
        return p

    def _case(self, expr: exp.Case) -> list[tuple[Formula, exp.Expr]]:
        """
        each arm with the condition to take it. In CASE x WHEN v, x is evaluated once and
        compared to each v with = (Postgres compares rows there as composite values).
        """
        this = expr.this
        xv = None if this is None else self._value(this)
        paths, none_taken = [], self.ctx.true
        for i in expr.args.get("ifs", []):
            if this is None or xv is None:
                t, _ = self.pred(i.this)
            else:
                t, _ = self._compare_values(exp.EQ, xv, self._value(i.this), this, i.this)
            paths.append((none_taken & t, i.args["true"]))
            none_taken &= ~t
        paths.append((none_taken, expr.args.get("default") or exp.Null()))
        return paths

    def _coalesce(self, items: list[exp.Expr]) -> Pred:
        """coalesce as predicate"""
        ctx = self.ctx
        true = false = ctx.false
        pending = ctx.true
        for item in items:
            t, f = self.pred(item)
            true |= pending & t
            false |= pending & f
            pending &= ~t & ~f
        return Pred(true, false)

    def _func(self, e: exp.Func):
        return self.ctx.fresh(Kind.MAYBE)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
