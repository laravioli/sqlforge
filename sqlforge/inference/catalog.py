from __future__ import annotations

from sqlforge.introspection.catalog import DEFAULT_SEARCH_PATH, Table, View, mapping_schema, sources
from sqlforge.introspection.structures import (
    CompositeKind,
    CompositeType,
    DomainType,
    PGType,
    PGTypeRegister,
)

from .relation import ViewStore


class Catalog:
    def __init__(self, type_register: PGTypeRegister, search_path=DEFAULT_SEARCH_PATH):
        self.search_path: tuple[str, ...] = search_path  # TODO: would need an override in config
        self.views = ViewStore()
        self.mapping_schema = self.mapping_schema = mapping_schema(type_register, search_path)

        self._types = type_register
        self._types_by_name: dict[tuple[str, str], PGType] = {
            (t.ns, t.name): t for t in type_register.values()
        }
        self._sources: dict[tuple[str, str], Table | View] = {
            (s.ns, s.name): s for s in sources(type_register)
        }

    def _resolve[T](self, types: dict[tuple[str, str], T], ns: str | None, typ: str) -> T | None:
        spaces = (ns,) if ns else self.search_path
        return next((t for s in spaces if (t := types.get((s, typ))) is not None), None)

    def lookup(self, typ: str, ns: str | None = None):
        return self._resolve(self._types_by_name, ns, typ)

    def source(self, key: tuple[str | None, str]):
        return self._resolve(self._sources, key[0], key[1])

    def relation(self, ns: str, name: str) -> CompositeType | None:
        """a relation in FROM, where column constraints hold"""
        t = self._types_by_name.get((ns, name))
        return t if isinstance(t, CompositeType) and t.comp_kind is not CompositeKind.TYPE else None

    def shape(self, oid: int) -> tuple[tuple[str, int], ...] | None:
        """(field name, field type oid) in order, or None if not composite."""
        t = self._domain(oid)
        if not isinstance(t, CompositeType):
            return None
        return tuple((a.name, a.attr_type) for a in t.attributes)  # list order, not position

    def _domain(self, oid: int) -> PGType:
        """Unwrap domains down to the real type."""
        t = self._types[oid]
        while isinstance(t, DomainType):
            t = self._types[t.basetype]
        return t
