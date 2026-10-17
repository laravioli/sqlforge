from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from sqlglot import exp

from .catalog import Oid, Shape
from .context import Context, Formula
from .eval import Evaluator
from .exception import UnknownColumn
from .notebook import Notebook
from .relation import Alias, ColKey, ColType, Item, Row, Subquery

type PredicateFormula = tuple[Formula, Formula]
type NullFormula = Formula


class ScopeProtocol(Protocol):
    ctx: Context
    side: list[Formula]
    notebook: Notebook

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...
    def shape(self, oid: Oid) -> Shape: ...


@dataclass(frozen=True, slots=True)
class Env:
    """
    A view of current null facts of a row, at this point of evaluation
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
        """the FROM item `alias`, and the env (scope) that owns it"""
        env: Env | None = self
        while env is not None:
            if (item := env.items.get(alias)) is not None:
                return item
            env = env.outer
        raise UnknownColumn((alias, "*"))

    def nulls(self, alias: Alias) -> Sequence[Formula]:
        """null formulas of every column of `alias`, in order"""
        return self.item(alias).nulls

    def padded(self, alias: Alias) -> Formula:
        """the whole row `alias` is NULL: only when an outer join padded it"""
        return self.item(alias).padded

    def null(self, key: ColKey) -> Formula:
        try:
            return self.item(key[0]).null(key[1])
        except KeyError:
            raise UnknownColumn(key)

    def type(self, key: ColKey) -> ColType:
        """oid from one row column or unknown (cte, derived table)"""
        try:
            return self.item(key[0]).type(key[1])
        except KeyError:
            raise UnknownColumn(key)
