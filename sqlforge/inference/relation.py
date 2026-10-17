from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from .catalog import Oid
from .context import Context, Formula, Kind
from .lattice import Nullability

type Alias = str
type Column = str
type ColKey = tuple[Alias, Column]  # alias.column
type ColType = Oid | Literal["unknown"]


def support(fs: Sequence[Formula]):
    return set().union(*(f.support for f in fs))


@dataclass(frozen=True, slots=True)
class Relation:
    """Result of a scope or a cte/table/view materialization"""

    ctx: Context
    columns: Sequence[str]
    nulls: Sequence[Formula]
    types: Sequence[ColType]
    invariant: Formula

    @property
    def is_empty(self) -> bool:
        return not self.ctx.sat(self.invariant)

    @property
    def formulas(self):
        """
        [*nulls, invariant]
        """
        return [*self.nulls, self.invariant]  # dont forget card when u add feature

    @property
    def support(self):
        return support(self.formulas)

    def result(self):
        sat, inv = self.ctx.sat, self.invariant
        return [Nullability(sat(inv & f), sat(inv & ~f)) for f in self.nulls]

    def compress(self):
        hidden = {
            v for v in (self.invariant.support - support(self.nulls)) if not self.ctx.is_global(v)
        }
        return (
            replace(self, invariant=self.ctx.bdd.exist(hidden, self.invariant)) if hidden else self
        )

    def row(self, alias: str):
        columns = self.columns
        return Row(
            {
                alias: Item(
                    columns,
                    self.nulls,
                    self.types,
                    self.ctx.false,
                    {c: columns.index(c) for c in columns},
                )
            },
            self.invariant,
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

        fresh = {
            v: ctx.fresh(ctx.kind(v))
            for v in sorted(rel.support, key=ctx.bdd.level_of_var)
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
class Item:
    """One FROM item inside a row"""

    columns: Sequence[Column]
    nulls: Sequence[Formula]
    types: Sequence[ColType]
    padded: Formula
    index: dict[Column, int]

    def null(self, column: Column) -> Formula:
        """Raise: KeyError"""
        return self.nulls[self.index[column]]

    def type(self, column: Column) -> ColType:
        """Raise: KeyError"""
        return self.types[self.index[column]]

    def pad(self, real: Formula) -> Item:
        return replace(
            self, nulls=[real.implies(n) for n in self.nulls], padded=real.implies(self.padded)
        )


@dataclass(frozen=True, slots=True)
class Row:
    """The row being transformed inside one scope"""

    items: Mapping[Alias, Item]
    invariant: Formula

    @staticmethod
    def unit(ctx: Context):
        return Row(items={}, invariant=ctx.true)


@dataclass(frozen=True, slots=True)
class Subquery:
    """A variant of relation for subquery in an expression"""

    relation: Relation
    empty: Formula  # subquery returns no row

    @property
    def scalar_null(self):
        # if is_single_row(e): NOTE: would be done with card analysis
        #     head = e.expressions[0].unalias()
        #     return ctx.false if isinstance(head, exp.Count) else ctx.fresh(Kind.MAYBE)
        return self.empty | self.relation.nulls[0]

    @property
    def nulls(self):
        return self.relation.nulls


class ViewStore:
    def __init__(self):
        self._ctx = Context()
        self._store: dict[tuple[str, str], StoredView] = {}

    def import_(self, dest: Context, key: tuple[str, str]) -> StoredView | None:
        """
        viewstore -> currrent analysis
        """
        view = self._store.get(key)
        if view is None:
            return

        src = self._ctx
        dest.declare(sorted(view.support, key=src.bdd.level_of_var))
        fs = src.copy(view.formulas, dest)

        return StoredView(nulls=fs[:-1], invariant=fs[-1])

    def export(self, src: Context, key: tuple[str, str], rel: Relation):
        """
        current analysis -> viewstore
        """
        rel = rel.compress()
        dest = self._ctx
        order = sorted(rel.support, key=src.bdd.level_of_var)
        rename = {v: f"_{Context.kind(v).value}{i}" for i, v in enumerate(order)}
        src.declare(rename.values())
        dest.declare(rename.values())
        fs = [src.bdd.let(rename, f) for f in rel.formulas] if rename else rel.formulas
        fs = src.copy(fs, dest)

        self._store[key] = StoredView(nulls=fs[:-1], invariant=fs[-1])


@dataclass
class StoredView:
    nulls: Sequence[Formula]
    invariant: Formula

    @property
    def formulas(self):
        """
        [*nulls, invariant]
        """
        return [*self.nulls, self.invariant]  # dont forget card when u add feature

    @property
    def support(self):
        return support([*self.nulls, self.invariant])
