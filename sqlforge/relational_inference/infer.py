from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer import Scope

from .catalog import Catalog
from .context import Context, Kind
from .eval import Env, Evaluator
from .exception import Unsupported
from .lattice import Nullability
from .relation import Relation, Row


class Analyzer:
    def __init__(self, ctx: Context, catalog: Catalog):
        self.ctx = ctx
        self.catalog = catalog
        self._cte_cache: dict[Scope, Relation] = {}

    def run(self, root: Scope) -> list[Nullability]:
        return self.query(root).result()

    def query(self, scope: Scope, env: Env | None = None) -> Relation:
        node = scope.expression

        match node:
            case exp.Select():
                return self.select(scope, env)
            case exp.SetOperation():
                pass
            case _:
                raise Unsupported(f"scope {type(node).__name__}")

        return Relation(ctx=self.ctx, columns=(), nulls=(), invariant=self.ctx.true)

    def select(self, scope: Scope, outer: Env | None = None):
        env = Env(parent=outer, ctx=self.ctx, row=Row.unit(self.ctx), notebook={})
        expression = scope.expression
        frm: exp.From | None = expression.args.get("from_")
        row = self.source(scope, frm.this, env) if frm is not None else Row.unit(self.ctx)

        return Relation(ctx=self.ctx, columns=(), nulls=(), invariant=self.ctx.true)

    def source(self, scope: Scope, node: exp.Expr, current_env: Env | None):
        alias = node.alias_or_name
        _, src = scope.selected_sources[alias]

        match node:
            case exp.Table() if isinstance(node.this, exp.Identifier):
                if isinstance(src, Scope):
                    return self._cte(src).cte(alias)
                else:
                    return self._scan(src)

            case exp.Subquery():
                return self.query(src, current_env.parent).compress().row(alias)  # type: ignore

            case exp.Lateral():
                return self.query(src.subquery_scopes[0], current_env).compress().row(alias)  # type: ignore

            case _:
                raise Unsupported(type(node).__name__)

    def _scan(self, tab: exp.Table) -> Row:
        table = self.catalog.tables.get(tab.name)
        if table is None:
            raise Unsupported(f"unknown table {tab.name}")
        nulls = {
            (tab.alias, name): self.ctx.fresh(Kind.BASE) if col.nullable else self.ctx.false
            for name, col in table.columns.items()
        }
        return Row(nulls=nulls, invariant=self.ctx.true)

    def _cte(self, cte_scope: Scope) -> Relation:
        rel = self._cte_cache.get(cte_scope)
        if rel is None:
            rel = self._cte_cache[cte_scope] = self.query(cte_scope).compress()
        return rel
