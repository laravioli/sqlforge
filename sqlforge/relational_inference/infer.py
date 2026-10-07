from __future__ import annotations

from functools import cached_property

from sqlglot import exp
from sqlglot.optimizer import Scope

from . import transfert as t
from .catalog import Catalog
from .context import Context, Formula, Kind
from .eval import Env
from .exception import Unsupported
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
        _ = Env(self, {}, self.outer)

        return Relation(
            ctx=self.ctx, columns=(), nulls=(), invariant=self.ctx.true & self.ctx.all(self.side)
        )

    @cached_property
    def _subqueries(self) -> dict[exp.Expr, Scope]:
        return {s.expression: s for s in self.scope.subquery_scopes}

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery:
        return Subquery(self.child(self._subqueries[expr], env), self.ctx.fresh(Kind.EMPTY))

    def source(
        self,
        node: exp.Table | exp.Subquery | exp.Lateral,
        env: Env,
    ) -> Row:
        alias = node.alias_or_name
        _, src = self.scope.selected_sources[alias]

        match node:
            case exp.Table() if isinstance(node.this, exp.Identifier):
                if isinstance(src, Scope):
                    return self.analyzer.cte(src, alias)
                else:
                    return self.analyzer.scan(src)

            case exp.Subquery():
                return self.child(src, self.outer).row(alias)  # type: ignore

            case exp.Lateral():
                return self.child(src.subquery_scopes[0], env).row(alias)  # type: ignore

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
