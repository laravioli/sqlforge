from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from sqlglot import exp

from .context import Context, Formula, Kind
from .exception import StarNotExpanded, UnknownColumn
from .expressions import (
    Comparison,
    is_boolean_expr,
    is_comparison,
    is_non_null_constant,
    is_row,
    is_strict_binary_operator,
    quantifier,
)
from .notebook import Notebook
from .relation import Key, Row, Subquery

type PredicateFormula = tuple[Formula, Formula]
type NullFormula = Formula


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


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env

    @property
    def ctx(self):
        return self.env.scope.ctx

    @property
    def notebook(self) -> Notebook:
        return self.env.scope.notebook

    def null(self, e: exp.Expr) -> NullFormula:
        ctx = self.ctx

        match e:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.null(this)

            case exp.Column(table=table, name=name):
                if e.is_star:
                    raise StarNotExpanded("c.* must be expanded")
                return self.env.null((table, name))

            case exp.TableColumn():
                return self.notebook.null("row", e) & ctx.all(self.env.fields(e.name))

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
                l_null, r_null = self.null(left), self.null(right)
                eq = self.notebook.compare(exp.EQ, left, right)
                return l_null | (~r_null & eq)

            case exp.Case():
                return ctx.any(taken & self.null(r) for taken, r in self._case(e))

            case _ if is_boolean_expr(e):
                return self._unknown(self.pred(e))

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

    def pred(self, e: exp.Expr) -> PredicateFormula:
        """
        dual-rail encoding:
            True:   (1,0)
            False:  (0,1)
            Unknow: (0,0)
        """

        ctx = self.ctx

        match e:
            case exp.Paren(this=this):
                return self.pred(this)

            case exp.And(this=left, expression=right):
                tl, fl = self.pred(left)
                tr, fr = self.pred(right)
                return tl & tr, fl | fr

            case exp.Or(this=left, expression=right):
                tl, fl = self.pred(left)
                tr, fr = self.pred(right)
                return tl | tr, fl & fr

            case exp.Not(this=this):
                t, f = self.pred(this)
                return f, t

            case exp.Null():
                return ctx.false, ctx.false

            case exp.Boolean(this=this):
                return (ctx.true, ctx.false) if this else (ctx.false, ctx.true)

            case exp.Is():
                return self._is(e)

            case _ if is_comparison(e):
                return self._compare(type(e), e.left, e.right)

            case exp.NullSafeEQ(this=left, expression=right):
                t = self._not_distinct(left, right)
                return (t, ~t)

            case exp.NullSafeNEQ(this=left, expression=right):
                t = self._not_distinct(left, right)
                return (~t, t)

            case exp.In():
                return self._in(e)

            case exp.Exists(this=query):
                sub = self._subquery(query.unnest())
                return ~sub.empty, sub.empty

            case exp.Case():
                paths = [(taken, self.pred(r)) for taken, r in self._case(e)]
                return (
                    ctx.any(taken & t for taken, (t, _) in paths),
                    ctx.any(taken & f for taken, (_, f) in paths),
                )

            case exp.Coalesce():
                return self._coalesce([e.this, *e.expressions])

            case exp.Between():
                # simplified by sqlglot
                return self._between(e)

            case _ if is_boolean_expr(e):
                # avoid infinite loop with null
                return self._fresh_pred()

            case _:
                return self._memorized(e)

    def _unknown(self, pred: PredicateFormula) -> NullFormula:
        """UNKNOWN as a null value"""
        t, f = pred
        return ~t & ~f

    def _fresh_pred(self) -> PredicateFormula:
        """fresh dual-rail encoding"""
        u, v = self.ctx.fresh(Kind.TRUTH), self.ctx.fresh(Kind.TRUTH)
        return u, ~u & v

    def _memorized(self, e: exp.Expr) -> PredicateFormula:
        known = ~self.null(e)
        holds = self.notebook.holds("value", e)
        return known & holds, known & ~holds

    # implement other comparison , add composite introspection
    def _compare(self, op: type[Comparison], left: exp.Expr, right: exp.Expr) -> PredicateFormula:
        if (q := quantifier(right)) is not None:
            return self._quantified(op, left, *q)

        match left, right:
            case _ if is_row(left) and is_row(right):
                return self._row_compare(op, left.expressions, right.expressions)

            case _ if is_row(left) or is_row(right):
                return self._fresh_pred()

            case (exp.Boolean() as lit, value) | (value, exp.Boolean() as lit) if op in (
                exp.EQ,
                exp.NEQ,
            ):
                t, f = self.pred(value)
                return (t, f) if lit.this == (op is exp.EQ) else (f, t)

            case _:
                return self._default_compare(op, left, right)

    def _default_compare(self, op: type[Comparison], x: exp.Expr, y: exp.Expr) -> PredicateFormula:
        known = ~self.null(x) & ~self.null(y)  # strict operator
        holds = self.notebook.compare(op, x, y)
        return known & holds, known & ~holds

    #  9.25.6 -> composite type op composite type (need another fn, and data introspection)
    #     he default behavior of the above operators is
    # the same as for IS [ NOT ] DISTINCT FROM for row constructors (see Section 9.25.5).
    # row_constructor IS NOT DISTINCT FROM row_constructor
    # This construct is similar to a = row comparison, but it does not yield null for null inputs. Instead, any
    # null value is considered unequal to (distinct from) any non-null value, and any two nulls are considered
    # equal (not distinct). Thus the result will always be either true or false, never null.
    def _composite_compare(
        self, op: type[Comparison], left: dict[str, NullFormula], right: dict[str, NullFormula]
    ) -> PredicateFormula:
        if op == exp.EQ or op == exp.NEQ:
            pass

        return self._fresh_pred()  # TODO

    def _row_compare(
        self,
        op: type[Comparison],
        left: Sequence[exp.Expr],
        right: Sequence[exp.Expr] | Subquery,
    ) -> PredicateFormula:

        ctx = self.ctx

        if isinstance(right, Subquery):
            # row op (subquery)
            empty = right.empty
            fresh_pred = self._fresh_pred()
            return ~empty & fresh_pred[0], ~empty & fresh_pred[1]
        else:
            # row op row
            pairs = list(zip(left, right, strict=True))

            match op:
                case exp.EQ:
                    preds = [self._compare(op, l, r) for l, r in pairs]
                    return ctx.all(t for t, _ in preds), ctx.any(f for _, f in preds)
                case exp.NEQ:
                    preds = [self._compare(op, l, r) for l, r in pairs]
                    return ctx.any(f for _, f in preds), ctx.all(t for t, _ in preds)
                case _:
                    # TODO
                    raise ValueError()

    # READ 9.24, 9.25.3/4 support array syntax  -> expression ALL Array[...]
    # subquery and array form (right hand side)
    # value or row constructor (left hand side), value can be a composite type
    # 4 combinaisons
    def _quantified(
        self, op: type[exp.Expr], left: exp.Expr, quantifier: Literal["any", "all"], inner: exp.Expr
    ) -> PredicateFormula:
        return self._fresh_pred()  # TODO

    # read 9.24.2/3, 9.25.1 9.25.2 -> subquery and (expression [,expression, ...]) form (right hand side)
    # value or row comparison (left hand side)
    # behave differently for comparison (9.25.5/6), in is = ANY (so be aware of row op row , composite value op composite value)
    def _in(self, expr: exp.Expr):
        return self._fresh_pred()  # TODO

    # re-check but i think only row as a special behavior, (other composite type are compared as is the value NULL)
    # 9.2
    def _is(self, expr: exp.Is) -> PredicateFormula:
        left, right, negate = expr.this, expr.expression, bool(expr.args.get("negate"))
        match right:
            case exp.Null():
                match left:
                    case _ if is_row(left):
                        fields = [self.null(x) for x in left.expressions]
                    case exp.TableColumn(name=name):
                        fields = self.env.fields(name)
                    case _:
                        n = self.null(left)
                        return (~n, n) if negate else (n, ~n)
                hit = self.ctx.all(~f for f in fields) if negate else self.ctx.all(fields)
                return hit, ~hit
            case exp.Boolean(this=value):
                t, f = self.pred(left)
                hit = t if value else f
                return (~hit, hit) if negate else (hit, ~hit)
        return self._fresh_pred()

    # composite type use the same rule as row (add this) 9.25.5/6, and it is composite = (<>) composite
    def _not_distinct(self, left: exp.Expr, right: exp.Expr):
        if is_row(left) and is_row(right):
            lr, rr = left.expressions, right.expressions
            # postgres would error if length mismatch
            return self.ctx.all(self._same(x, y) for x, y in zip(lr, rr, strict=True))
        else:
            return self._same(left, right)

    def _same(self, left: exp.Expr, right: exp.Expr) -> Formula:
        nl, nr = self.null(left), self.null(right)
        return (nl & nr) | (~nl & ~nr & self.notebook.compare(exp.EQ, left, right))

    def _between(self, e: exp.Between) -> PredicateFormula:
        x, low, high = e.this, e.args["low"], e.args["high"]
        (t1, f1), (t2, f2) = self._compare(exp.GTE, x, low), self._compare(exp.LTE, x, high)
        true, false = t1 & t2, f1 | f2
        if e.args.get("symmetric"):
            (t3, f3), (t4, f4) = self._compare(exp.GTE, x, high), self._compare(exp.LTE, x, low)
            true, false = true | (t3 & t4), false & (f3 | f4)
        return true, false

    def _test(self, op: type[exp.Expr], *operands: exp.Expr) -> PredicateFormula:
        known = self.ctx.all(~self.null(o) for o in operands)
        holds = self.notebook.holds(op.__name__, *operands)
        return known & holds, known & ~holds

    def _case(self, expr: exp.Case) -> list[tuple[Formula, exp.Expr]]:
        this = expr.this
        paths, none_taken = [], self.ctx.true
        for i in expr.args.get("ifs", []):
            cond = i.this if this is None else exp.EQ(this=this.copy(), expression=i.this.copy())
            t, _ = self.pred(cond)
            paths.append((none_taken & t, i.args["true"]))
            none_taken &= ~t
        paths.append((none_taken, expr.args.get("default") or exp.Null()))
        return paths

    def _coalesce(self, items: list[exp.Expr]) -> PredicateFormula:
        """coalesce as predicate"""
        ctx = self.ctx
        true = false = ctx.false
        pending = ctx.true
        for item in items:
            t, f = self.pred(item)
            true |= pending & t
            false |= pending & f
            pending &= ~t & ~f
        return true, false

    def _func(self, e: exp.Func):
        return self.ctx.fresh(Kind.MAYBE)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
