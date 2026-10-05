from __future__ import annotations

from sqlglot.optimizer import Scope

from .catalog import Catalog
from .context import Context
from .lattice import Nullability
from .relation import Relation


class Analyzer:
    def __init__(self, ctx: Context, catalog: Catalog):
        self.ctx = ctx
        self.catalog = catalog
        self._relations: dict[Scope, Relation] = {}

    def run(self, root: Scope) -> list[Nullability]:
        # analysis will be there
        return []

    def query(self, scope: Scope):
        pass
