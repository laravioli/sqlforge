from __future__ import annotations

from functools import cached_property, reduce
from typing import cast, overload

from sqlglot import exp
from sqlglot.optimizer import Scope

from . import transfert as t
from .catalog import Catalog
from .context import Context, Formula, Kind
from .eval import Env
from .exception import Unsupported
from .expression import is_join_group, is_plain_aggregate
from .relation import Relation, Row, Subquery, Template


class ScopedAnalyzer:
    def __init__(self, analyzer: Analyzer, scope: Scope, outer: Env | None):
        self.analyzer = analyzer
        self.scope = scope
        self.outer = outer
        self.ctx = analyzer.ctx
        self.side: list[Formula] = []
        self.notebook: dict[exp.Expr, Formula] = {}

    def analyse(self):
        scope = self.scope
        match scope.expression:
            case exp.Select():
                relation = self.select()
            case exp.SetOperation() as node:
                left, right = (self.child(s, self.outer) for s in scope.set_operation_scopes)
                relation = t.setop(node, left, right)
            case node:
                raise Unsupported(f"scope {type(node).__name__}")
        keep = scope.is_correlated_subquery or scope.is_root
        return relation if keep else relation.compress()

    def child(self, scope: Scope, outer: Env | None):
        """
        Analyse a child scope
                Params:
                    scope: child to analyse, parent is paused and wait for the analysis
                    outer: the env you want the child to look for external column
        """
        return type(self)(self.analyzer, scope, outer).analyse()

    def select(self) -> Relation:
        row = self._from()
        row = self._where(row)
        row = self._group_by(row)
        row = self._having(row)
        row = self._window(row)

        return self._project(row)

    def _from(self):
        select = self.scope.expression
        from_ = select.args.get("from_")
        if from_ is None:
            return Row.unit(self.ctx)
        return self._join(select, Env(self, {}, self.outer))

    def _join(self, expr: exp.Expr, env: Env) -> Row:
        """
        Rules:

        - JOIN is left-associative and binds tighter than the comma:
          a, b RIGHT JOIN c  =  a × (b ⟖ c)        a is never padded
        - a LATERAL item sees every FROM item on its left; an ON sees only its two operands.
        """
        match expr:
            case exp.Select():
                left = self._join(expr.args.get("from_").this, env)  # type: ignore
            case _ if is_join_group(expr):
                left = self._join(expr.this, env)  # resolve to a subquery
            case exp.Table() | exp.Subquery():
                left = self.source(expr)
            case exp.Lateral():
                left = self.source(expr, env)
            case _:
                raise Unsupported(f"{expr} is not supported in a join")

        joins = expr.args.get("joins")
        if not joins:
            return left

        def step(acc: tuple[Row, Row], join: exp.Join) -> tuple[Row, Row]:
            # closed: the comma trees already finished, left: the one being built
            closed, left = acc
            if t.JoinKind.from_expr(join) is t.JoinKind.COMMA:
                closed = t.cross(closed, left)
                right = self._join(join.this, env.extend(closed))
                return closed, right

            right = self._join(join.this, env.extend(closed, left))
            on = join.args.get("on")

            if on is not None:
                t_on, _ = env.bind(left, right).evaluator().pred(on)
            else:
                t_on = self.ctx.true
            return closed, t.join(self.ctx, join, left, right, t_on)

        closed, tree = reduce(step, joins, (Row.unit(self.ctx), left))
        return t.cross(closed, tree)

    def _where(self, row: Row):
        where = self.scope.expression.args.get("where")
        if where is None:
            return row
        t_where, _ = Env(self, row.nulls, self.outer).evaluator().pred(where.this)
        return t.filter_(row, t_where)

    def _group_by(self, row: Row):
        if is_plain_aggregate(self.scope.expression):  # type: ignore
            no_input_row = self.ctx.fresh(Kind.EMPTY)
            return Row(nulls=row.nulls, invariant=(~no_input_row).implies(row.invariant))
        return row

    def _having(self, row: Row):
        return row

    def _window(self, row: Row):
        return row

    def _project(self, row: Row) -> Relation:
        select = cast(exp.Select, self.scope.expression)
        ev = Env(self, row.nulls, self.outer).evaluator()

        return Relation(
            ctx=self.ctx,
            columns=[e.alias_or_name for e in select.selects],
            nulls=[ev.null(e) for e in select.selects],
            invariant=row.invariant & self.ctx.all(self.side),
        )

    @cached_property
    def _subqueries(self) -> dict[exp.Expr, Scope]:
        return {s.expression: s for s in self.scope.subquery_scopes}

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery:
        return Subquery(self.child(self._subqueries[expr], env), self.ctx.fresh(Kind.EMPTY))

    @overload
    def source(self, node: exp.Table | exp.Subquery, outer: None = None) -> Row: ...
    @overload
    def source(self, node: exp.Lateral, outer: Env) -> Row: ...
    def source(
        self,
        node: exp.Table | exp.Subquery | exp.Lateral,
        outer: Env | None = None,
    ) -> Row:
        alias = node.alias_or_name
        if alias not in self.scope.selected_sources:
            raise Unsupported(f"source {type(node).__name__} {alias!r}")

        _, src = self.scope.selected_sources[alias]

        match node:
            case exp.Table() if isinstance(node.this, exp.Identifier):
                if isinstance(src, Scope):
                    return self.analyzer.cte(src, alias)
                else:
                    return self.analyzer.scan(src)

            case exp.Subquery():
                return self.child(src, self.outer).row(alias)  # type: ignore

            case exp.Lateral() if isinstance(node.this, exp.Subquery):  # not LATERAL fn
                return self.child(src.subquery_scopes[0], outer).row(alias)  # type: ignore

            case _:
                raise Unsupported(f"source {type(node).__name__}")


class Analyzer:
    def __init__(
        self,
        ctx: Context,
        catalog: Catalog,
    ):
        self.ctx = ctx
        self.catalog = catalog
        self._cte_cache: dict[Scope, Template] = {}
        self._catalog_cache: dict[str, Template] = {}

    def run(self, scope: Scope):
        return ScopedAnalyzer(self, scope, None).analyse()

    def scan(self, tab: exp.Table) -> Row:
        template = self._catalog_cache.get(tab.name)

        if template is None:
            table = self.catalog.tables[tab.name]
            relation = Relation(
                ctx=self.ctx,
                columns=tuple(table.columns.keys()),
                nulls=[
                    self.ctx.fresh(Kind.BASE) if col.nullable else self.ctx.false
                    for col in table.columns.values()
                ],
                invariant=self.ctx.true,
            )  # compression is not needed
            template = Template(relation)
            self._catalog_cache[tab.name] = template
            return relation.row(tab.alias)

        return template.materialize().row(tab.alias)

    def cte(self, cte_scope: Scope, alias: str) -> Row:
        template = self._cte_cache.get(cte_scope)

        if template is None:
            relation = self.run(cte_scope)
            template = self._cte_cache[cte_scope] = Template(relation)
            return relation.row(alias)

        return template.materialize().row(alias)
