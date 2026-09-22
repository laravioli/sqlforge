from __future__ import annotations

from enum import Enum, auto
from functools import cache
from itertools import product


class BottomException(Exception):
    """
    raise Bottom exception in place of a bottom element
    """


class NullSet(Enum):
    MAYBE_NULL = auto()
    NON_NULL = auto()
    NULL = auto()

    @property
    def can_be_null(self) -> bool:
        return self is not NullSet.NON_NULL

    def __or__(self: NullSet, y: NullSet) -> NullSet:
        """
        `join` operation
        """
        if self is y:
            return self
        return NullSet.MAYBE_NULL

    def __and__(self: NullSet, y: NullSet) -> NullSet:
        """
        `meet` operation
        """
        if self is y:
            return self
        elif self is NullSet.MAYBE_NULL:
            return y
        elif y is NullSet.MAYBE_NULL:
            return self
        else:
            raise BottomException()

    def __sub__(self, _: NullSet):
        return self


class Boolean(Enum):
    TRUE = auto()
    FALSE = auto()
    UNKNOWN = auto()

    @property
    def is_true(self) -> bool:
        return self is Boolean.TRUE

    def __or__(self, y: Boolean) -> Boolean:
        """
        logical `OR`
        """
        if self == Boolean.TRUE or y == Boolean.TRUE:
            return Boolean.TRUE

        if self == Boolean.UNKNOWN or y == Boolean.UNKNOWN:
            return Boolean.UNKNOWN

        return Boolean.FALSE

    def __and__(self, y: Boolean) -> Boolean:
        """
        logical `AND`
        """
        if self == Boolean.FALSE or y == Boolean.FALSE:
            return Boolean.FALSE

        if self == Boolean.UNKNOWN or y == Boolean.UNKNOWN:
            return Boolean.UNKNOWN

        return Boolean.TRUE

    def __invert__(self) -> Boolean:
        """
        logical `NOT`
        """
        match self:
            case Boolean.UNKNOWN:
                return self
            case Boolean.FALSE:
                return Boolean.TRUE
            case Boolean.TRUE:
                return Boolean.FALSE


class BooleanSet(Enum):
    TOP = frozenset(Boolean)
    TRUE_OR_FALSE = frozenset({Boolean.TRUE, Boolean.FALSE})
    TRUE_OR_UNKNOWN = frozenset({Boolean.TRUE, Boolean.UNKNOWN})
    FALSE_OR_UNKNOWN = frozenset({Boolean.FALSE, Boolean.UNKNOWN})
    TRUE = frozenset({Boolean.TRUE})
    FALSE = frozenset({Boolean.FALSE})
    UNKNOWN = frozenset({Boolean.UNKNOWN})

    @property
    def can_be_true(self) -> bool:
        return Boolean.TRUE in self.value

    @property
    def can_be_unknown(self) -> bool:
        return Boolean.UNKNOWN in self.value

    @cache
    def __or__(self: BooleanSet, y: BooleanSet):
        """
        logical `OR`
        """
        return BooleanSet(frozenset(a | b for a, b in product(self.value, y.value)))

    @cache
    def __and__(self: BooleanSet, y: BooleanSet):
        """
        logical `AND`
        """
        return BooleanSet(frozenset(a & b for a, b in product(self.value, y.value)))

    @cache
    def __invert__(self):
        """
        logical `NOT`
        """
        return BooleanSet(frozenset(~a for a in self.value))

    def to_nullset(self) -> NullSet:
        if self == BooleanSet.UNKNOWN:
            return NullSet.NULL
        if self.can_be_unknown:
            return NullSet.MAYBE_NULL
        return NullSet.NON_NULL
