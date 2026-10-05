from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sqlglot import exp

from .context import Context, Formula, Kind, VarName
from .lattice import Nullability

if TYPE_CHECKING:
    from .eval import Env


@dataclass(frozen=True, slots=True)
class Relation:
    """Abstract representation of scope output"""

    ctx: Context
    columns: Sequence[str]
    nulls: Sequence[Formula]
    invariant: Formula
    card: None = None  # tbd

    def result(self):
        return [
            Nullability(self.ctx.sat(self.invariant & f), self.ctx.sat(self.invariant & ~f))
            for f in self.nulls
        ]

    def row(self, alias: str, placeholders: Mapping[str, Formula] | None = None):
        """build a row from a relation source"""
        fresh = self._fresh(placeholders)
        return Row(
            nulls={(alias, k): v for k, v in zip(fresh.columns, fresh.nulls)},
            invariant=fresh.invariant,
        )

    def _fresh(self, placeholders: Mapping[VarName, Formula] | None = None):
        """replace local and placeholder vars in order to use Relation as a Row"""
        support = set(self.invariant.support).union(*(f.support for f in self.nulls))
        placeholders = placeholders or {}
        d = {}
        ctx = self.ctx

        for v in sorted(support, key=ctx.bdd.level_of_var):
            if v in placeholders:
                d[v] = placeholders[v]
                continue

            kind = ctx.kind(v)
            if kind is Kind.PLACEHOLDER:
                raise KeyError(v)
            elif kind is not Kind.PARAM:
                d[v] = self.ctx.fresh(kind)

        if not d:
            return self

        let = lambda f: ctx.bdd.let(d, f)
        return replace(self, nulls=tuple(map(let, self.nulls)), invariant=let(self.invariant))

    def compress(self):
        visible = set().union(*(f.support for f in self.nulls))
        hidden = {v for v in self.invariant.support - visible if not self.ctx.is_global(v)}
        return (
            replace(self, invariant=self.ctx.bdd.exist(hidden, self.invariant)) if hidden else self
        )


type Key = tuple[str, str]  # alias.column


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

    _relation: Relation
    placeholders: dict[exp.Column, VarName]

    def resolve(self, env: Env):
        formulas: dict[VarName, Formula] = {}
        for col, var in self.placeholders.items():
            formulas[var] = env.column_formula(col)

        rel = self._relation._fresh(formulas)
        eps = rel.ctx.fresh(Kind.EMPTY)

        return eps, (~eps).implies(rel.invariant)
