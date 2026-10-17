from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlforge.introspection.catalog import DEFAULT_SEARCH_PATH, Table, View, mapping_schema, sources
from sqlforge.introspection.structures import (
    CompositeType,
    DomainType,
    Oid,
    PGType,
    PGTypeRegister,
)

from .relation import ViewStore


class Catalog:
    def __init__(self, type_register: PGTypeRegister, search_path=DEFAULT_SEARCH_PATH):
        self.search_path: tuple[str, ...] = search_path  # TODO: would need an override in config
        self.views = ViewStore()
        self.mapping_schema = mapping_schema(type_register, search_path)

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

    def pg_type(self, key: tuple[str | None, str]):
        """
        resolve (ns,type) as a postgres type
        """
        return self._resolve(self._types_by_name, key[0], key[1])

    def source(self, key: tuple[str | None, str]):
        """
        resolve (ns,type) as a source
        """
        return self._resolve(self._sources, key[0], key[1])

    def shape(self, oid: Oid) -> Shape:
        t = self._unwrap_domain(oid)
        if t is None:
            return "unknown"
        if not isinstance(t, CompositeType):
            return "scalar"
        return Composite(tuple((a.name, a.attr_type) for a in t.attributes))

    def _unwrap_domain(self, oid: Oid) -> PGType | None:
        """
        Unwrap domains down to the real type; None if the OID isn't in the register.
        """
        t = self._types.get(oid)
        while isinstance(t, DomainType):
            t = self._types.get(t.basetype)
        return t


type Shape = Composite | Literal["scalar", "unknown"]

type Fields = tuple[tuple[str, Oid], ...]


@dataclass(frozen=True, slots=True)
class Composite:
    fields: Fields
