from __future__ import annotations

from functools import cached_property, reduce
from typing import cast, overload

from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer import Scope

from . import transfert as t
from .catalog import Catalog, Oid, Shape, Table, View
from .context import Context, Formula, Kind
from .eval import Env, Notebook
from .exception import Unsupported
from .expressions import is_join_group, is_plain_aggregate
from .prepare import prepare_view
from .relation import ColKey, Relation, Row, Subquery, Template


class ScopedAnalyzer:
    def __init__(self, analyzer: Analyzer, scope: Scope, outer: Env | None):
        self.analyzer = analyzer
        self.scope = scope
        self.outer = outer
        self.ctx = analyzer.ctx
        self.side: list[Formula] = []
        self.notebook: Notebook = Notebook(self.ctx, None)
        self.row_types: dict[ColKey, Oid] = {}

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
                    self._add_source_types((node.db or None, node.name), alias)
                    return self.analyzer.scan(src, alias)

            case exp.Subquery():
                return self.child(src, self.outer).row(alias)  # type: ignore

            case exp.Lateral() if isinstance(node.this, exp.Subquery):  # not LATERAL fn
                return self.child(src.subquery_scopes[0], outer).row(alias)  # type: ignore

            case _:
                raise Unsupported(f"source {type(node).__name__}")

    def _add_source_types(self, key: tuple[str | None, str], alias: str):
        src = self.analyzer.catalog.source(key)
        if src is not None:
            self.row_types.update({(alias, k): v.attr_type for k, v in src.columns.items()})

    def shape(self, oid: Oid) -> Shape:
        return self.analyzer.catalog.shape(oid)


class Analyzer:
    def __init__(
        self,
        ctx: Context,
        catalog: Catalog,
    ):
        self.ctx = ctx
        self.catalog = catalog
        self._cte_cache: dict[Scope, Template] = {}
        self._scan_cache: dict[tuple[str | None, str], Template] = {}

    def run(self, scope: Scope):
        return ScopedAnalyzer(self, scope, None).analyse()

    def scan(self, tab: exp.Table, alias: str) -> Row:
        key = (tab.db or None, tab.name)
        template = self._scan_cache.get(key)

        if template is not None:
            return template.materialize().row(alias)

        source = self.catalog.source(key)
        match source:
            case Table() as table:
                relation = self._table_relation(table)

            case View() as view:
                relation = self._view_relation(view)

            case None:
                raise Unsupported(f"Unknown source {key}")

        self._scan_cache[key] = Template(relation)
        return relation.row(alias)

    def _table_relation(self, source: Table) -> Relation:
        return Relation(
            ctx=self.ctx,
            columns=tuple(source.columns.keys()),
            nulls=[
                self.ctx.fresh(Kind.BASE) if source.maybe_null(col.name) else self.ctx.false
                for col in source.columns.values()
            ],
            invariant=self.ctx.true,
        )
        # compression is not needed

    def _view_relation(self, view: View) -> Relation:
        key = (view.ns, view.name)
        stored_view = self.catalog.views.import_(self.ctx, key)
        if stored_view is not None:
            return Template(
                Relation(
                    ctx=self.ctx,
                    columns=tuple(view.columns),
                    nulls=stored_view.nulls,
                    invariant=stored_view.invariant,
                )
            ).materialize()

        try:
            relation = self.run(prepare_view(view, self.catalog.mapping_schema))
        except (SqlglotError, Unsupported):
            relation = Relation(  # view we can't analyze: every column may be NULL
                ctx=self.ctx,
                columns=tuple(view.columns),
                nulls=[self.ctx.fresh(Kind.MAYBE) for _ in view.columns],
                invariant=self.ctx.true,
            )
        self.catalog.views.export(self.ctx, key, relation)
        return relation

    def cte(self, cte_scope: Scope, alias: str) -> Row:
        template = self._cte_cache.get(cte_scope)

        if template is None:
            relation = self.run(cte_scope)
            template = self._cte_cache[cte_scope] = Template(relation)
            return relation.row(alias)

        return template.materialize().row(alias)


# Star expansion rules
# The composite_value.* syntax results in column expansion of this kind when it appears at
# the top level of a SELECT output list, a RETURNING list in INSERT/UPDATE/DELETE/MERGE,
# a VALUES clause, or a row constructor. In all other contexts (including when nested inside one of
# those constructs), attaching .* to a composite value does not change the value, since it means “all
# columns” and so the same composite value is produced again.
