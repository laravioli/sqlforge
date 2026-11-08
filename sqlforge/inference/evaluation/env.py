from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from sqlglot import exp

from sqlforge.inference.context import Context, Formula
from sqlforge.inference.exception import UnknownColumn
from sqlforge.inference.relation import Alias, Item, Row, Subquery

from .evaluator import Evaluator
from .notebook import Notebook

type PredicateFormula = tuple[Formula, Formula]
type NullFormula = Formula


class ScopeProtocol(Protocol):
    ctx: Context
    side: list[Formula]
    notebook: Notebook

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...


@dataclass(frozen=True, slots=True)
class Env:
    """
    A view of the current row, at this point of evaluation
    """

    scope: ScopeProtocol
    items: Mapping[Alias, Item]
    outer: Env | None

    def evaluator(self):
        return Evaluator(self)

    def bind(self, *rows: Row) -> Env:
        return replace(
            self,
            items={a: i for row in rows for a, i in row.items.items()},
        )

    def extend(self, *rows: Row) -> Env:
        return replace(
            self,
            items={a: i for row in (self, *rows) for a, i in row.items.items()},
        )

    def item(self, alias: Alias) -> Item:
        """the FROM item `alias`"""
        env: Env | None = self
        while env is not None:
            if (item := env.items.get(alias)) is not None:
                return item
            env = env.outer
        raise UnknownColumn((alias, "*"))
