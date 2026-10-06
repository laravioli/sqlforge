from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from sqlglot import exp

from .context import Context, Formula
from .exception import UnknownColumn
from .relation import Row, Subquery


@dataclass
class Env:
    parent: Env | None
    row: Row  # current row resolution
    _resolve: Callable[[Env, exp.Select | exp.SetOperation], Subquery]
    notebook: dict[exp.Expr, Formula] = field(default_factory=dict)

    def next(self, row: Row):
        return replace(self, row=row)

    def get_subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        return self._resolve(self, expr)

    def column_formula(self, key: tuple[str, str]) -> Formula:
        ancestor = self

        while ancestor is not None:
            formula = ancestor.row.nulls.get(key)
            if formula is not None:
                return formula
            ancestor = ancestor.parent

        raise UnknownColumn()


class Evaluator:
    ctx: Context
    env: Env
    side: list[Formula]

    @property
    def notebook(self) -> dict[exp.Expr, Formula]:
        return self.env.notebook

    def side_formula(self) -> Formula:
        return self.ctx.all(self.side)

    def null(self, e: exp.Expr) -> Formula:
        return self.ctx.true

    def pred(self, e: exp.Expr) -> tuple[Formula, Formula]:
        return (self.ctx.true, self.ctx.true)
