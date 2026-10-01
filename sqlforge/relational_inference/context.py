try:
    import dd.cudd as _bdd
except ImportError:
    import dd.autoref as _bdd

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    BASE = "base"
    VALUE = "value"
    MAYBE = "maybe"
    MATCHED = "matched"
    EMPTY = "empty"
    UNION = "union"
    PARTITION = "partition"
    PLACEHOLDER = "placeholder"
    PARAM = "param"


GLOBAL_KINDS = frozenset({Kind.PARAM, Kind.PLACEHOLDER})


@dataclass(frozen=True)
class AtomInfo:
    kind: Kind
    label: str


class Context:
    def __init__(self):
        self.bdd = _bdd.BDD()
        self.bdd.configure(reordering=True)
        self.true = self.bdd.true
        self.false = self.bdd.false
        self._counter = 0

    def fresh(self, name: str) -> _bdd.Function:
        var = f"{name}_{self._counter}"
        self._counter += 1
        self.bdd.declare(var)
        return self.bdd.var(var)

    def var(self, name: str) -> _bdd.Function:
        return self.bdd.var(name)
