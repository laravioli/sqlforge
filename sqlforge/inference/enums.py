from __future__ import annotations

from collections.abc import Callable
from enum import Enum, auto
from itertools import product


class Nullability(Enum):
    NON_NULL = auto()
    NULL = auto()
    MAYBE_NULL = auto()

    def __bool__(self):
        return self is not Nullability.NON_NULL


class SqlBool(Enum):
    TRUE = auto()
    FALSE = auto()
    UNKNOWN = auto()

    def __bool__(self):
        # NOTE one exception to this is check constraint that accept TRUE or UNKNOW as True
        return self == SqlBool.TRUE

    def __or__(self, other) -> SqlBool:
        if self == SqlBool.TRUE or other == SqlBool.TRUE:
            return SqlBool.TRUE

        if self == SqlBool.UNKNOWN or other == SqlBool.UNKNOWN:
            return SqlBool.UNKNOWN

        return SqlBool.FALSE

    def __and__(self, other) -> SqlBool:
        if self == SqlBool.FALSE or other == SqlBool.FALSE:
            return SqlBool.FALSE

        if self == SqlBool.UNKNOWN or other == SqlBool.UNKNOWN:
            return SqlBool.UNKNOWN

        return SqlBool.TRUE

    def __invert__(self) -> SqlBool:
        match self:
            case SqlBool.UNKNOWN:
                return self
            case SqlBool.FALSE:
                return SqlBool.TRUE
            case SqlBool.TRUE:
                return SqlBool.FALSE


def lift1[T](op: Callable[[T], SqlBool], x: set[T] | frozenset[T]):
    return frozenset(op(_) for _ in x)


def lift2[T, V](op: Callable[[T, V], SqlBool], x: set[T] | frozenset[T], y: set[V] | frozenset[V]):
    return frozenset(op(a, b) for a, b in product(x, y))
