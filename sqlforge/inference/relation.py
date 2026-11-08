from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from sqlforge.introspection.structures import Oid

from .context import Context, Formula, Kind
from .lattice import Nullability

type Alias = str
type Column = str
type ColKey = tuple[Alias, Column]  # alias.column
type TypeOid = Oid | Literal["unknown"]


def support(fs: Sequence[Formula]):
    return set().union(*(f.support for f in fs))


@dataclass(frozen=True, slots=True)
class Col:
    null: Formula
    type: TypeOid

    def map(self, f: Callable[[Formula], Formula]) -> Col:  # rename, copy, pad
        """transform null formula"""
        return replace(self, null=f(self.null))


@dataclass(frozen=True, slots=True)
class Relation:
    """Result of a scope or a cte/table/view materialization"""

    ctx: Context
    names: tuple[str, ...]
    columns: tuple[Col, ...]
    invariant: Formula

    @property
    def is_empty(self) -> bool:
        return not self.ctx.sat(self.invariant)

    @property
    def nulls(self):
        return tuple(c.null for c in self.columns)

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
            v
            for v in (self.invariant.support - support(self.nulls))
            if not self.ctx.is_global(v)
        }
        return (
            replace(self, invariant=self.ctx.bdd.exist(hidden, self.invariant))
            if hidden
            else self
        )

    def row(self, alias: str):
        columns = self.columns
        names = self.names
        return Row(
            {
                alias: Item(
                    names,
                    columns,
                    self.ctx.false,
                    {name: names.index(name) for name in names},
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


@dataclass(frozen=True, slots=True)
class Row:
    """The row being transformed inside one scope"""

    items: Mapping[Alias, Item]
    invariant: Formula

    @staticmethod
    def unit(ctx: Context):
        return Row(items={}, invariant=ctx.true)


@dataclass(frozen=True, slots=True)
class Item:
    names: tuple[str, ...]
    columns: tuple[Col, ...]
    padded: Formula
    _index: dict[str, int]

    @property
    def null(self) -> Formula:
        return self.padded

    @property
    def nulls(self):
        return tuple(c.null for c in self.columns)

    def col(self, column: Column):
        return self.columns[self._index[column]]

    def null_of(self, column: Column) -> Formula:
        """Raise: KeyError"""
        return self.columns[self._index[column]].null

    def type_of(self, column: Column) -> TypeOid:
        """Raise: KeyError"""
        return self.columns[self._index[column]].type

    def pad(self, real: Formula) -> Item:
        return replace(
            self,
            columns=tuple(col.map(real.implies) for col in self.columns),
            padded=real.implies(self.padded),
        )


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
            columns=tuple(col.map(let) for col in rel.columns),
            invariant=let(rel.invariant),
        )


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

        return StoredView(
            columns=tuple(
                col.map(lambda _, i=i: fs[i]) for i, col in enumerate(view.columns)
            ),
            invariant=fs[-1],
        )

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

        self._store[key] = StoredView(
            columns=tuple(
                col.map(lambda _, i=i: fs[i]) for i, col in enumerate(rel.columns)
            ),
            invariant=fs[-1],
        )


@dataclass
class StoredView:
    columns: tuple[Col, ...]
    invariant: Formula

    @property
    def nulls(self):
        return tuple(c.null for c in self.columns)

    @property
    def formulas(self):
        """
        [*nulls, invariant]
        """
        return [*self.nulls, self.invariant]  # dont forget card when u add feature

    @property
    def support(self):
        return support(self.formulas)
