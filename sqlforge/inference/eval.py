from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlglot import exp

from .catalog import Composite, Shape
from .context import Formula, Kind
from .exception import StarNotExpanded
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
from .relation import ColType, Subquery

if TYPE_CHECKING:
    from .env import Env

type PredicateFormula = tuple[Formula, Formula]
type NullFormula = Formula


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
                return self.env.padded(e.name)

            # NOTE: function will also use Dot
            case exp.Dot(this=exp.TableColumn() as row, expression=field):  # (t).f is t.f
                return self.env.null((row.name, field.name))

            case exp.Dot(this=base):  # (composite).f
                match self._shape(base):
                    case "scalar":
                        all_set = all_null = ctx.false
                    case shape:
                        all_set, all_null = self._may_composite(base, shape)
                return self.null(base) | (~all_set & (all_null | self.notebook.null("field", e)))

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
                return self._between(e)

            case _ if is_boolean_expr(e):
                # avoid infinite loop with null
                return self._fresh_pred()

            case _:
                return self._memorized(e)

    def type(self, e: exp.Expr) -> ColType:
        """
        catalog type of a column or of a field at the end of a path
                Returns:
                    pg_type oid or unknown
        """
        match e:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.type(this)

            case exp.Column(table=alias, name=col):
                return self.env.type((alias, col))

            case exp.Cast():
                return "unknown"

            case exp.Dot(this=exp.TableColumn() as row, expression=field):  # (t).f is t.f
                return self.env.type((row.name, field.name))

            case exp.Dot(this=base, expression=field):
                match self._shape(base):
                    case Composite(fields=fields):
                        return dict(fields).get(field.name, "unknown")

        return "unknown"

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

    def _shape(self, e: exp.Expr) -> Shape:
        oid = self.type(e)
        return "unknown" if oid == "unknown" else self.env.scope.shape(oid)

    def _may_composite(
        self, e: exp.Expr, shape: Composite | Literal["unknown"]
    ) -> PredicateFormula:
        match shape:
            case Composite(fields=()):  # no field: both tests hold
                all_non_null = all_null = self.ctx.true
            case Composite() | "unknown":
                all_non_null, all_null = (
                    self.notebook.holds("all_non_null", e),
                    self.notebook.holds("all_null", e),
                )
                if type(shape) is Composite:
                    all_null &= ~all_non_null

        return all_non_null, all_null

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

        match left, right:
            case _, Subquery():
                empty = right.empty
                fresh_pred = self._fresh_pred()
                return ~empty & fresh_pred[0], ~empty & fresh_pred[1]

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
                    # TODO: lexicographic, decided at the first unequal or NULL pair
                    return self._fresh_pred()

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

    def _is(self, expr: exp.Is) -> PredicateFormula:
        left, right, negate = expr.this.unnest(), expr.expression, bool(expr.args.get("negate"))

        match right:
            case exp.Null():
                return self._is_null(left, negate)
            case exp.Boolean(this=value):
                return self._is_true(left, value, negate)
            case _:
                return self._fresh_pred()

    def _is_null(self, expr: exp.Expr, negate: bool) -> PredicateFormula:
        match expr:
            case _ if is_row(expr):
                nulls = [self.null(x) for x in expr.expressions]
                true = self.ctx.all(~n for n in nulls) if negate else self.ctx.all(nulls)
                return true, ~true

            case exp.TableColumn(name=alias):
                nulls = self.env.nulls(alias)
                true = self.ctx.all(~n for n in nulls) if negate else self.ctx.all(nulls)
                return true, ~true

            case _:
                n = self.null(expr)
                match self._shape(expr):
                    case "scalar":
                        return (~n, n) if negate else (n, ~n)
                    case shape:
                        all_non_null, all_null = self._may_composite(expr, shape)
                true = ~n & all_non_null if negate else n | all_null
                return true, ~true

    def _is_true(self, expr: exp.Expr, true: bool, negate: bool):
        t, f = self.pred(expr)
        hit = t if true else f
        return (~hit, hit) if negate else (hit, ~hit)

    # composite type use the same rule as row (add this) 9.25.5/6, and it is composite = (<>) composite
    def _not_distinct(self, left: exp.Expr, right: exp.Expr):
        if is_row(left) and is_row(right):
            lr, rr = left.expressions, right.expressions
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
