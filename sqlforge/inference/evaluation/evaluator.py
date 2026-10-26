from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlglot import exp

from sqlforge.inference.catalog import Composite
from sqlforge.inference.context import Formula, Kind
from sqlforge.inference.exception import StarNotExpanded
from sqlforge.inference.relation import Subquery

from .notebook import ALL_NULL, ALL_SET, CONCAT, DOTTED_FIELD, PRED, UNKNOWN, Notebook
from .structures import KeyedItem, Opaque, Pred, Scalar, Tuple, Value
from .syntax import (
    Comparison,
    is_boolean_expr,
    is_cast_row,
    is_comparison,
    is_non_null_constant,
    is_row,
    is_scalar,
    is_strict_binary_operator,
    is_strict_binary_predicate,
    quantifier,
)
from .types import TypeEval

if TYPE_CHECKING:
    from .env import Env


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env
    types: TypeEval

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
            case exp.Dot(
                this=exp.TableColumn() as row, expression=field
            ):  # (t).f is t.f
                return self.env.null_of((row.name, field.name))

            case exp.Dot(this=base):  # (composite).f
                match self._value(base):
                    case Opaque(null=null, key=key):
                        return null | (
                            ~self.notebook.holds(ALL_SET, key)
                            & (
                                self.notebook.holds(ALL_NULL, key)
                                | (self.notebook.null(DOTTED_FIELD, e))
                            )
                        )
                    case _:  # (ROW(a, b)).f1: rare, stay unknown
                        return ctx.fresh(Kind.MAYBE)

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
                return l.null | self._compare_values(exp.EQ, l, r).t

            case exp.Case():
                return ctx.any(taken & self.null(then) for taken, then in self._case(e))

            case _ if is_boolean_expr(e):
                return self.pred(e).as_null

            case exp.Neg(this=this) | exp.BitwiseNot(this=this):
                return self.null(this)

            case exp.Cast(this=this):
                return self.null(this)

            case exp.DPipe(this=l, expression=r):
                return self.notebook.null(CONCAT, e) & (self.null(l) | self.null(r))

            case _ if is_strict_binary_operator(e):
                return self.null(e.this) | self.null(e.expression)

            case (
                exp.Array()
                | exp.CurrentDate()
                | exp.CurrentTime()
                | exp.CurrentTimestamp()
                | exp.Localtime()
                | exp.Localtimestamp()
            ):
                return ctx.false

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
                p = Pred.binary(ctx.true)
                return p if truth else ~p

            case exp.Is():
                return self._is(e)

            case exp.Expr(left=l, right=r) if is_comparison(e):
                if (q := quantifier(r)) is not None:
                    return self._quantified(type(e), l, *q)
                else:
                    return self._compare(type(e), self._value(l), self._value(r))

            case exp.NullSafeEQ(left=l, right=r):
                return Pred.binary(self._not_distinct(l, r))

            case exp.NullSafeNEQ(left=l, right=r):
                return Pred.binary(~self._not_distinct(l, r))

            case exp.In():
                return self._in(e)

            case exp.Exists(this=query):
                sub = self._subquery(query.unnest())
                return Pred.binary(~sub.empty)

            case exp.Case():
                return self._branches(
                    [(taken, self.pred(then)) for taken, then in self._case(e)]
                )

            case exp.Coalesce():
                return self._coalesce([e.this, *e.expressions])

            case exp.Between():
                return self._between(e)

            case _ if is_strict_binary_predicate(e):
                return Pred.known(
                    holds=self.notebook.holds(PRED, e),
                    known=~self.null(e.this) & ~self.null(e.expression),
                )

            case _:
                return Pred.known(
                    holds=self.notebook.holds(PRED, e),
                    known=(
                        ~self.notebook.null(UNKNOWN, e)
                        if is_boolean_expr(e)
                        else ~self.null(e)
                    ),
                )

    def _all(self, ps: Sequence[Pred]):
        return Pred(self.ctx.all(p.t for p in ps), self.ctx.any(p.f for p in ps))

    def _any(self, ps: Sequence[Pred]):
        return Pred(self.ctx.any(p.t for p in ps), self.ctx.all(p.f for p in ps))

    def _value(self, e: exp.Expr) -> Value:
        """
        wrap an expression and his nullability in a `Value`, using catalog when needed
        """
        e = e.unnest()
        match e:
            case exp.TableColumn(name=alias):
                item = self.env.item(alias)
                return KeyedItem(item.null, item.fields, e)

            case x if is_row(x):
                return Tuple(self.ctx.false, x.expressions, self.null, x)

            case x if is_scalar(x):
                return Scalar(self.null(x), x)

            case x:
                shape = self.types.shape(x)
                match shape:
                    case "scalar":
                        return Scalar(self.null(x), x)
                    case Composite() | "unknown":
                        return Opaque(self.null(x), shape, x)

    def _compare(self, op: type[Comparison], l: Value, r: Value) -> Pred:
        match l, r:
            case (Tuple(), Tuple()):
                return self._compare_rows(op, l, r)

            case (Tuple(), Opaque(key=exp.Select() | exp.SetOperation())):
                return Pred.fresh(self.ctx)

            case _:
                return self._compare_values(op, l, r)

    def _compare_values(self, op: type[Comparison], l: Value, r: Value) -> Pred:
        """
        record operator record (9.25.6)
        """
        if op in (exp.EQ, exp.NEQ):
            eq = self._are_values_equal(l, r)
            holds = eq if op is exp.EQ else ~eq
        else:
            holds = self.notebook.compare(op, l.key, r.key)

        return Pred.known(holds, ~l.null & ~r.null)

    def _are_values_equal(self, l: Value, r: Value) -> Formula:
        """equality of two non-NULL values; NULL fields compare equal"""
        match l, r:
            case Tuple(args=lk), Tuple(args=rk):
                return self.ctx.all(
                    self._not_distinct(x, y) for x, y in zip(lk, rk, strict=True)
                )

            case Tuple() | KeyedItem(), Tuple() | KeyedItem():
                same_nulls = self.ctx.all(
                    (nl & nr) | (~nl & ~nr)
                    for nl, nr in zip(l.fields, r.fields, strict=True)
                )
                return same_nulls & self.notebook.compare(exp.EQ, l.key, r.key)

            case _:
                return self.notebook.compare(exp.EQ, l.key, r.key)

    def _not_distinct(self, left: exp.Expr, right: exp.Expr) -> Formula:
        l, r = self._value(left), self._value(right)
        return (l.null & r.null) | (~l.null & ~r.null & self._are_values_equal(l, r))

    def _compare_rows(
        self,
        op: type[Comparison],
        l: Tuple,
        r: Tuple,
        lv: Sequence[Value] | None = None,
    ) -> Pred:
        """
        row_constructor operator row_constructor (9.25.5)
        """
        ctx = self.ctx
        pairs = list(
            zip(
                [self._value(k) for k in l.args] if lv is None else lv,
                [self._value(k) for k in r.args],
                strict=True,
            )
        )
        eq = [self._compare_values(exp.EQ, a, b) for a, b in pairs]

        match op:
            case exp.EQ:
                return self._all(eq)
            case exp.NEQ:
                return ~self._all(eq)

        strict = exp.LT if op in (exp.LT, exp.LTE) else exp.GT
        paths: Sequence[tuple[Formula, Pred]] = []
        equal_so_far = ctx.true

        for (a, b), (eq_t, eq_f) in zip(pairs, eq):
            paths.append(
                (equal_so_far & eq_f, self._compare_values(strict, a, b))
            )  # first unequal pair decides
            equal_so_far &= eq_t
        paths.append(
            (
                equal_so_far,
                Pred.binary(ctx.true if op in (exp.LTE, exp.GTE) else ctx.false),
            )
        )
        return self._branches(paths)

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
        - a subquery is summarized (_quantify_unseen); a ROW(...) on the left compares field by field.
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
                preds = [self._compare_values(op, l, self._value(i)) for i in items]
                return self._any(preds) if quantifier == "any" else self._all(preds)

            case exp.Subquery() | exp.Select() | exp.SetOperation():
                while isinstance(inner, exp.Subquery):
                    inner = inner.this
                sub = self._subquery(inner)  # type: ignore[arg-type]
                if is_cast_row(left):
                    return Pred.fresh(ctx)
                can_null = any(ctx.sat(sub.relation.invariant & n) for n in sub.nulls)
                match self._value(left):
                    case Tuple(
                        fields=fields
                    ):  # written ROW(...): one NULL-ness per field
                        lnulls = fields
                    case l:
                        lnulls = [l.null]
                return self._quantify_unseen(
                    op, quantifier, lnulls, sub.empty, can_null
                )

            case (
                _
            ):  # an array value: its elements may be NULL, so the result may be NULL
                p = self._quantify_unseen(
                    op,
                    quantifier,
                    [self._value(left).null],
                    ctx.fresh(Kind.EMPTY),
                    True,
                )
                return p.when(~self.null(inner))

    def _quantify_unseen(
        self,
        op: type[Comparison],
        quantifier: Literal["any", "all"],
        lnulls: Sequence[Formula],
        empty: Formula,
        can_null: bool,
    ) -> Pred:

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
        left = e.this
        if (query := e.args.get("query")) is not None:
            return self._quantified(exp.EQ, left, "any", query)

        if not e.expressions or any(is_cast_row(x) for x in (left, *e.expressions)):
            return Pred.fresh(self.ctx)  # IN UNNEST(...) isn't Postgres, or a cast row

        l = self._value(left)
        return self._any(
            [self._compare(exp.EQ, l, self._value(i)) for i in e.expressions]
        )

    def _is(self, e: exp.Is) -> Pred:
        left, right, negate = e.this, e.expression, bool(e.args.get("negate"))

        match right:
            case exp.Null():
                match self._value(left):
                    case (
                        KeyedItem(null=null, fields=fields)
                        | Tuple(null=null, fields=fields)
                    ):
                        return Pred.binary(
                            null | self.ctx.all(fields)
                            if not negate
                            else ~null & self.ctx.all(~f for f in fields)
                        )

                    case Scalar(null=null):
                        return Pred.binary(null if not negate else ~null)

                    case Opaque(null=null, key=key):
                        return Pred.binary(
                            null | self.notebook.holds(ALL_NULL, key)
                            if not negate
                            else ~null & self.notebook.holds(ALL_SET, key)
                        )

            case exp.Boolean() as b:
                t, f = self.pred(left)
                holds = t if b.to_py() else f
                return Pred.binary(~holds if negate else holds)

            case _:
                return Pred.fresh(self.ctx)

    def _between(self, e: exp.Between) -> Pred:
        x, low, high = e.this, e.args["low"], e.args["high"]
        xv, lv, hv = (
            self._value(x),
            self._value(low),
            self._value(high),
        )  # each evaluated once
        p = self._compare(exp.GTE, xv, lv) & self._compare(exp.LTE, xv, hv)
        if e.args.get("symmetric"):
            p |= self._compare(exp.GTE, xv, hv) & self._compare(exp.LTE, xv, lv)
        return p

    def _branches(self, paths: Sequence[tuple[Formula, Pred]]) -> Pred:
        """the Pred of the branch that is taken; no branch taken is NULL"""
        return Pred(
            self.ctx.any(taken & p.t for taken, p in paths),
            self.ctx.any(taken & p.f for taken, p in paths),
        )

    def _case(self, expr: exp.Case) -> Sequence[tuple[Formula, exp.Expr]]:
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
                t, _ = self._compare_values(exp.EQ, xv, self._value(i.this))
            paths.append((none_taken & t, i.args["true"]))
            none_taken &= ~t
        paths.append((none_taken, expr.args.get("default") or exp.Null()))
        return paths

    def _coalesce(self, items: Sequence[exp.Expr]) -> Pred:
        """the first argument that isn't NULL decides"""
        paths, null_so_far = [], self.ctx.true
        for item in items:
            p = self.pred(item)
            paths.append((null_so_far & ~p.as_null, p))
            null_so_far &= p.as_null
        return self._branches(paths)

    def _func(self, e: exp.Func):
        return self.ctx.fresh(Kind.MAYBE)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
