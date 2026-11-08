from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar, Literal, NamedTuple

from sqlglot import exp

from sqlforge.inference.catalog import Composite
from sqlforge.inference.context import Context, Formula, Kind
from sqlforge.inference.relation import Col, Item, Shape

type NullFormula = Formula
type PredicateFormula = tuple[Formula, Formula]


class Pred(NamedTuple):
    """
    dual-rail encoding:
        True:   (1,0)
        False:  (0,1)
        Unknow: (0,0)
    """

    t: Formula
    f: Formula

    def __and__(self, b: Pred):
        return Pred(self.t & b.t, self.f | b.f)

    def __or__(self, b: Pred):
        return Pred(self.t | b.t, self.f & b.f)

    def __invert__(self):
        return Pred(self.f, self.t)

    @property
    def as_null(self):
        return ~self.t & ~self.f

    def when(self, cond: Formula):
        return Pred(cond & self.t, cond & self.f)

    @staticmethod
    def binary(true: Formula):
        return Pred(true, ~true)

    @staticmethod
    def known(holds: Formula, known: Formula) -> Pred:
        """the result is unknown if known is false else the result is bool(holds)"""
        return Pred(known & holds, known & ~holds)

    @staticmethod
    def fresh(ctx: Context) -> Pred:
        u, v = ctx.fresh(Kind.TRUTH), ctx.fresh(Kind.TRUTH)
        return Pred(u, ~u & v)


@dataclass(frozen=True)
class Scalar:
    shape: ClassVar[Literal["scalar"]] = "scalar"

    null: Formula
    key: exp.Expr


@dataclass(frozen=True, slots=True)
class KeyedItem:
    item: Item
    key: exp.Expr

    @property
    def null(self):
        return self.item.null

    @property
    def shape(self) -> Shape:
        return "unknown"

    @property
    def fields(self):
        return self.item.nulls


@dataclass(frozen=True)
class Tuple:
    shape: ClassVar[Literal["unknown"]] = "unknown"

    null: Formula  # ctx.false
    args: Sequence[exp.Expr]
    _null_of: Callable[[exp.Expr], Formula]
    key: exp.Expr

    @cached_property
    def fields(self) -> Sequence[Formula]:
        return [self._null_of(k) for k in self.args]


@dataclass(frozen=True, slots=True)
class Opaque:
    """a composite whose fields are unknown: column, function, Dot, CASE... or an unknown value"""

    null: Formula
    shape: Composite | Literal["unknown"]
    key: exp.Expr


type Value = Scalar | KeyedItem | Tuple | Opaque


def to_col(v: Value) -> Col:
    return Col(v.null, v.shape)
