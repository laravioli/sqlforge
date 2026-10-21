from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from sqlglot import exp

from sqlforge.inference.catalog import Catalog
from sqlforge.inference.context import Context, Formula
from sqlforge.inference.exception import UnknownColumn
from sqlforge.inference.relation import Alias, ColKey, ColType, Item, Row, Subquery

from .evaluator import Evaluator
from .notebook import Notebook
from .type_evaluator import TypeEvaluator

type PredicateFormula = tuple[Formula, Formula]
type NullFormula = Formula


class ScopeProtocol(Protocol):
    ctx: Context
    catalog: Catalog
    side: list[Formula]
    notebook: Notebook

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...


@dataclass(frozen=True, slots=True)
class Env:
    """
    A view of current null facts of a row, at this point of evaluation
    """

    scope: ScopeProtocol
    items: Mapping[Alias, Item]
    outer: Env | None

    def evaluator(self):
        return Evaluator(self, TypeEvaluator(self, self.scope.catalog))

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

    def fields(self, alias: Alias) -> Sequence[Formula]:
        """null formulas of every column of `alias`, in order"""
        return self.item(alias).fields

    def null(self, alias: Alias) -> Formula:
        """the whole row `alias` is NULL: only when an outer join padded it"""
        return self.item(alias).padded

    def null_of(self, key: ColKey) -> Formula:
        """nullability of (alias,col) from current row"""
        try:
            return self.item(key[0]).null_of(key[1])
        except KeyError:
            raise UnknownColumn(key)

    def col_oid(self, key: ColKey) -> ColType:
        """oid from one row column or unknown (cte, derived table)"""
        try:
            return self.item(key[0]).type_of(key[1])
        except KeyError:
            raise UnknownColumn(key)
