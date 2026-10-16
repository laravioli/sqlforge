from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlforge.introspection.catalog import Table, View, mapping_schema, sources
from sqlforge.introspection.structures import (
    CompositeKind,
    CompositeType,
    DomainType,
    PGType,
    PGTypeRegister,
)

from .context import Context, Formula
from .relation import Relation, support


class Catalog:
    def __init__(self, type_register: PGTypeRegister, search_path=("pg_catalog", "public")):

        self._types = type_register
        self._types_by_name: dict[tuple[str, str], PGType] = {
            (t.ns, t.name): t for t in type_register.values()
        }
        self.search_path: tuple[str, ...] = search_path  # TODO: would need an override in config
        self._sources: dict[tuple[str, str], Table | View] = {
            (s.ns, s.name): s for s in sources(type_register)
        }
        self.views = ViewStore()
        self.mapping_schema = mapping_schema(register=type_register)

    def _resolve[T](self, table: dict[tuple[str, str], T], ns: str | None, name: str) -> T | None:
        spaces = (ns,) if ns else self.search_path
        return next((t for s in spaces if (t := table.get((s, name))) is not None), None)

    def lookup(self, key: tuple[str | None, str]):
        return self._resolve(self._types_by_name, key[0], key[1])

    def source(self, key: tuple[str | None, str]):
        return self._resolve(self._sources, key[0], key[1])

    def domain(self, oid: int) -> PGType:
        """Unwrap domains down to the real type."""
        t = self._types[oid]
        while isinstance(t, DomainType):
            t = self._types[t.basetype]
        return t

    def relation(self, ns: str, name: str) -> CompositeType | None:
        """a relation in FROM, where column constraints hold"""
        t = self._types_by_name.get((ns, name))
        return t if isinstance(t, CompositeType) and t.comp_kind is not CompositeKind.TYPE else None

    def shape(self, oid: int) -> tuple[tuple[str, int], ...] | None:
        """(field name, field type oid) in order, or None if not composite."""
        t = self.domain(oid)
        if not isinstance(t, CompositeType):
            return None
        return tuple((a.name, a.attr_type) for a in t.attributes)  # list order, not position


class ViewStore:
    def __init__(self):
        self._ctx = Context()
        self._store: dict[tuple[str, str], StoredView] = {}

    def import_(self, dest: Context, key: tuple[str, str]) -> Relation | None:
        """
        viewstore -> currrent analysis
        """
        view = self._store.get(key)
        if view is None:
            return

        src = self._ctx
        dest.declare(sorted(view.support, key=src.bdd.level_of_var))
        fs = src.copy(view.formulas, dest)

        return Relation(ctx=dest, columns=view.columns, nulls=fs[:-1], invariant=fs[-1])

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

        self._store[key] = StoredView(columns=rel.columns, nulls=fs[:-1], invariant=fs[-1])


@dataclass
class StoredView:
    columns: Sequence[str]
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
