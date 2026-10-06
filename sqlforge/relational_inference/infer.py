from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer import Scope

from .catalog import Catalog
from .context import Context, Kind
from .eval import Env
from .exception import Unsupported
from .lattice import Nullability
from .relation import Relation, Row, Subquery, Template
from .transfert import setop


class Analyzer:
    def __init__(self, ctx: Context, catalog: Catalog):
        self.ctx = ctx
        self.catalog = catalog
        self._cte_cache: dict[Scope, Template] = {}
        self._catalog_cache: dict[str, Template] = {}

    def run(self, root: Scope) -> list[Nullability]:
        return self.query(root, outer_env=None).result()

    def query(self, scope: Scope, *, outer_env: Env | None) -> Relation:
        """
        Analysis of one scope
            Returns:
                    A compressed Relation object
        """
        node = scope.expression

        match node:
            case exp.Select():
                relation = self.select(scope, outer_env=outer_env)
            case exp.SetOperation():
                left = self.query(scope.set_operation_scopes[0], outer_env=outer_env)
                right = self.query(scope.set_operation_scopes[1], outer_env=outer_env)
                relation = setop(node, left, right)
            case _:
                raise Unsupported(f"scope {type(node).__name__}")

        return relation.compress() if not scope.is_correlated_subquery else relation

    def select(self, scope: Scope, *, outer_env: Env | None):

        env = self._new_env(scope, outer_env)
        expression = scope.expression

        frm: exp.From | None = expression.args.get("from_")
        if frm is not None:
            env = env.next(self.source(scope, frm.this, env))

        return Relation(ctx=self.ctx, columns=(), nulls=(), invariant=self.ctx.true)

    def source(
        self, scope: Scope, node: exp.Table | exp.Subquery | exp.Lateral, current_env: Env | None
    ) -> Row:
        alias = node.alias_or_name
        _, src = scope.selected_sources[alias]

        match node:
            case exp.Table() if isinstance(node.this, exp.Identifier):
                if isinstance(src, Scope):
                    return self._cte(src, alias)
                else:
                    return self._scan(src)

            case exp.Subquery():
                return self.query(src, outer_env=current_env.parent).row(alias)  # type: ignore

            case exp.Lateral():
                return self.query(src.subquery_scopes[0], outer_env=current_env).row(alias)  # type: ignore

            case _:
                raise Unsupported(f"source {type(node).__name__}")

    def _scan(self, tab: exp.Table) -> Row:
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

    def _cte(self, cte_scope: Scope, alias: str) -> Row:
        template = self._cte_cache.get(cte_scope)

        if template is None:
            relation = self.query(cte_scope, outer_env=None)
            template = self._cte_cache[cte_scope] = Template(relation)
            return relation.row(alias)

        return template.materialize().row(alias)

    def _new_env(self, scope: Scope, outer_env: Env | None):

        mapping = {s.expression: s for s in scope.subquery_scopes}

        def get_subquery(env: Env, expr: exp.Select | exp.SetOperation) -> Subquery:
            relation = self.query(mapping[expr], outer_env=env)
            return Subquery(relation, self.ctx.fresh(Kind.EMPTY))

        return Env(outer_env, Row.unit(self.ctx), get_subquery)
