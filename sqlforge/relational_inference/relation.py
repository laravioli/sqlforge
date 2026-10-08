from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .context import Context, Formula, Kind
from .lattice import Nullability

type Alias = str
type Column = str
type Key = tuple[Alias, Column]  # alias.column


@dataclass(frozen=True, slots=True)
class Relation:
    """Result of a scope or a cte/table materialization"""

    ctx: Context
    columns: Sequence[str]
    nulls: Sequence[Formula]
    invariant: Formula

    @property
    def is_empty(self) -> bool:
        return not self.ctx.sat(self.invariant)

    def result(self):
        sat, inv = self.ctx.sat, self.invariant
        return [Nullability(sat(inv & f), sat(inv & ~f)) for f in self.nulls]

    def compress(self):
        visible = set().union(*(f.support for f in self.nulls))
        hidden = {v for v in (self.invariant.support - visible) if not self.ctx.is_global(v)}
        return (
            replace(self, invariant=self.ctx.bdd.exist(hidden, self.invariant)) if hidden else self
        )

    def row(self, alias: str):
        return Row(
            nulls={(alias, k): v for k, v in zip(self.columns, self.nulls)},
            invariant=self.invariant,
        )

    def subquery(self, empty: bool | None):
        if empty is True:
            eps = self.ctx.true
        elif empty is False:
            eps = self.ctx.false
        else:
            eps = self.ctx.fresh(Kind.EMPTY)
        return Subquery(self, eps)


@dataclass(frozen=True)
class Template:
    """Factory of cte/table relation"""

    _relation: Relation

    def materialize(self):
        rel = self._relation
        ctx = rel.ctx
        support = set(rel.invariant.support).union(*(f.support for f in rel.nulls))

        fresh = {
            v: ctx.fresh(ctx.kind(v))
            for v in sorted(support, key=ctx.bdd.level_of_var)
            if not ctx.is_global(v)
        }

        if not fresh:
            return rel

        let = lambda f: ctx.bdd.let(fresh, f)
        return replace(
            rel,
            nulls=list(map(let, rel.nulls)),
            invariant=let(rel.invariant),
        )


@dataclass(frozen=True, slots=True)
class Row:
    """The row being transformed inside one scope"""

    nulls: Mapping[Key, Formula]
    invariant: Formula

    @staticmethod
    def unit(ctx: Context):
        return Row(nulls={}, invariant=ctx.true)


@dataclass(frozen=True, slots=True)
class Subquery:
    """A variant of relation for subquery in an expression"""

    relation: Relation
    empty: Formula  # subquery returns no row

    @property
    def scalar_null(self):
        return self.empty | self.relation.nulls[0]
