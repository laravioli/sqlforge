from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from .catalog import Catalog
from .context import Context
from .relation import Template


class Engine:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog


class Analyzer:
    def __init__(self, ctx: Context, catalog: Catalog):
        self.ctx = ctx
        self.catalog = catalog
        self.summaries: dict[Scope, Template] = {}

    def analyze(self, sql: exp.Expr) -> Analysis:
        return Analysis()


class Analysis:
    pass
