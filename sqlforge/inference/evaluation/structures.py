from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from sqlglot import exp

from sqlforge.inference.catalog import Composite
from sqlforge.inference.context import Formula
from sqlforge.inference.relation import Item

type NullFormula = Formula
type PredicateFormula = tuple[Formula, Formula]


class Pred(NamedTuple):
    t: Formula
    f: Formula

    def __and__(self, b: Pred):
        return Pred(self.t & b.t, self.f | b.f)

    def __or__(self, b: Pred):
        return Pred(self.t | b.t, self.f & b.f)

    def __invert__(self):
        return Pred(self.f, self.t)

    @staticmethod
    def of(holds: Formula, known: Formula | None = None) -> Pred:
        """two-valued if known is None, else NULL when not known"""
        return Pred(holds, ~holds) if known is None else Pred(known & holds, known & ~holds)


@dataclass(frozen=True)
class Scalar:
    null: Formula


@dataclass(frozen=True, slots=True)
class Tuple:
    null: Formula  # ctx.false
    keys: Sequence[exp.Expr]
    _null_of: Callable[[exp.Expr], Formula] = field(repr=False, compare=False)

    @property
    def fields(self) -> Sequence[Formula]:
        return [self._null_of(k) for k in self.keys]


@dataclass(frozen=True)
class Opaque:
    """a composite whose fields are unknown: column, function, Dot, CASE... or an unknown value"""

    null: Formula
    key: exp.Expr  # notebook key for the "all set" / "all null" / "field f" facts
    shape: Composite | Literal["unknown"]  # field names and oids when the catalog knows them


type Value = Scalar | Item | Tuple | Opaque
