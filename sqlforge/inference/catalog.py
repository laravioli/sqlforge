from __future__ import annotations

from typing import NewType

from sqlforge.introspection.catalog import (
    DEFAULT_SEARCH_PATH,
    Table,
    View,
    mapping_schema,
    sources,
)
from sqlforge.introspection.structures import (
    ArrayType,
    CompositeType,
    DomainType,
    Oid,
    PGType,
    PGTypeRegister,
    PseudoType,
)

from .relation import ViewStore
from .structures import Array, Composite, Shape

PGKey = NewType("PGKey", tuple[str | None, str])


class Catalog:
    def __init__(self, pg_types: PGTypeRegister, search_path=DEFAULT_SEARCH_PATH):
        self.search_path: tuple[str, ...] = (
            search_path  # TODO: would need an override in config
        )
        self.views = ViewStore()
        self.mapping_schema = mapping_schema(pg_types, search_path)

        self._types = pg_types
        self._types_by_name: dict[tuple[str, str], PGType] = {
            (t.ns, t.name): t for t in pg_types.values()
        }
        self._sources: dict[tuple[str, str], Table | View] = {
            (s.ns, s.name): s for s in sources(pg_types)
        }
        self._shapes: dict[Oid, Shape] = {}

    def _resolve[T](
        self, types: dict[tuple[str, str], T], ns: str | None, typ: str
    ) -> T | None:
        spaces = (ns,) if ns else self.search_path
        return next((t for s in spaces if (t := types.get((s, typ))) is not None), None)

    def pg_type(self, key: PGKey):
        """
        resolve (ns,type) as a postgres type
        """
        return self._resolve(self._types_by_name, key[0], key[1])

    def source(self, key: PGKey):
        """
        resolve (ns,type) as a source
        """
        return self._resolve(self._sources, key[0], key[1])

    def shape(self, key: int | PGKey) -> Shape:
        if not isinstance(key, int):
            pg_type = self.pg_type(key)
            if pg_type is None:
                return "unknown"
            key = pg_type.oid

        s = self._shapes.get(key)
        if s is None:
            t = self._unwrap_domain(key)
            if t is None or isinstance(t, PseudoType):
                s = "unknown"
            elif isinstance(t, ArrayType):
                s = Array(self.shape(t.elemtype))
            elif not isinstance(t, CompositeType):
                s = "scalar"
            else:
                s = Composite(
                    tuple((a.name, self.shape(a.attr_type)) for a in t.attributes)
                )
            self._shapes[key] = s
        return s

    def _unwrap_domain(self, oid: Oid) -> PGType | None:
        """
        Unwrap domains down to the real type; None if the OID isn't in the register.
        """
        t = self._types.get(oid)
        while isinstance(t, DomainType):
            t = self._types.get(t.basetype)
        return t
