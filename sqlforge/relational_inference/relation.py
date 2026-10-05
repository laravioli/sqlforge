from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from .context import Context, Formula, Kind
from .lattice import Nullability

type Key = tuple[str, str]  # alias.column


@dataclass(frozen=True, slots=True)
class Relation:
    ctx: Context
    columns: Sequence[str]
    nulls: Sequence[Formula]
    invariant: Formula
    card: None = None  # tbd

    @property
    def is_empty(self) -> bool:
        return not self.ctx.sat(self.invariant)

    def result(self):
        sat, inv = self.ctx.sat, self.invariant
        return [Nullability(sat(inv & f), sat(inv & ~f)) for f in self.nulls]

    def compress(self):
        visible = set().union(*(f.support for f in self.nulls))
        hidden = {v for v in self.invariant.support - visible if not self.ctx.is_global(v)}
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

    def cte(self, alias: str):
        ctx = self.ctx
        support = set(self.invariant.support).union(*(f.support for f in self.nulls))
        definitions = {}

        for v in sorted(support, key=ctx.bdd.level_of_var):
            kind = ctx.kind(v)
            if not ctx.is_global(v):
                definitions[v] = ctx.fresh(kind)

        if not definitions:
            return self.row(alias)

        let = lambda f: ctx.bdd.let(definitions, f)
        return Row(
            nulls={(alias, k): v for k, v in zip(self.columns, map(let, self.nulls))},
            invariant=let(self.invariant),
        )


@dataclass(frozen=True, slots=True)
class Row:
    """Abstract representation of a row during sql execution"""

    nulls: Mapping[tuple[str, str], Formula]
    invariant: Formula

    @staticmethod
    def unit(ctx: Context):
        return Row(nulls={}, invariant=ctx.true)


@dataclass(frozen=True, slots=True)
class Subquery:
    """A variant of relation for subquery in an expression"""

    relation: Relation
    empty: Formula  # subquery returns no row
