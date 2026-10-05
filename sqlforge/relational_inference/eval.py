from __future__ import annotations

from dataclasses import dataclass, replace

from sqlglot import exp

from .context import Context, Formula
from .exception import UnknownColumn
from .relation import Row


@dataclass
class Env:
    parent: Env | None
    ctx: Context
    row: Row  # current row resolution
    notebook: dict[exp.Expr, Formula]

    def next(self, row: Row):
        return replace(self, row=row)

    def column_formula(self, column: exp.Column):
        ancestor = self
        key = (column.table, column.name)

        while ancestor is not None:
            formula = ancestor.row.nulls.get(key)
            if formula is not None:
                return formula
            ancestor = ancestor.parent

        raise UnknownColumn()


class Evaluator:
    pass
