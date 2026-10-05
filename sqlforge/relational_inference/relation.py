from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from .context import Context, Formula, Kind, VarName
from .lattice import Nullability

type Key = tuple[str, str]  # alias.column


@dataclass(frozen=True, slots=True)
class Relation:
    """Abstract representation of scope output"""

    ctx: Context
    columns: Sequence[str]
    nulls: Sequence[Formula]
    invariant: Formula
    externals: dict[VarName, Key] = field(default_factory=dict)
    card: None = None  # tbd

    @property
    def is_empty(self) -> bool:
        return not self.ctx.sat(self.invariant)

    def compress(self):
        visible = set().union(*(f.support for f in self.nulls))
        hidden = {v for v in self.invariant.support - visible if not self.ctx.is_global(v)}
        return (
            replace(self, invariant=self.ctx.bdd.exist(hidden, self.invariant)) if hidden else self
        )

    def row(self, alias: str, lookup: Callable[[Key], Formula]):
        """build a row from a relation source"""
        fresh = self._copy(lookup)
        return Row(
            nulls={(alias, k): v for k, v in zip(fresh.columns, fresh.nulls)},
            invariant=fresh.invariant,
        )

    def subquery(self, lookup: Callable[[Key], Formula]):
        fresh = self._copy(lookup)
        eps = self.ctx.fresh(Kind.EMPTY)
        return Subquery(fresh, eps)

    def _copy(self, lookup: Callable[[Key], Formula]):  # lookup come from Env
        """replace local and placeholder vars in order to use Relation as a Row or Subquery"""
        ctx = self.ctx
        support = set(self.invariant.support).union(*(f.support for f in self.nulls))
        definitions = {k: lookup(v) for k, v in self.externals.items()}

        for v in sorted(support, key=ctx.bdd.level_of_var):
            kind = ctx.kind(v)

            match kind:
                case Kind.PLACEHOLDER | Kind.PARAM:
                    continue
                case _:
                    definitions[v] = ctx.fresh(kind)

        if not definitions:
            return self

        let = lambda f: ctx.bdd.let(definitions, f)
        return replace(self, nulls=tuple(map(let, self.nulls)), invariant=let(self.invariant))

    def result(self):
        sat, inv = self.ctx.sat, self.invariant
        return [Nullability(sat(inv & f), sat(inv & ~f)) for f in self.nulls]


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
