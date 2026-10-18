from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import dd.autoref as _bdd
else:
    try:
        import dd.cudd as _bdd
    except ImportError:
        import dd.autoref as _bdd

from collections.abc import Iterable, Sequence
from enum import Enum
from string import digits

type Formula = _bdd.Function
type VarName = str

from contextlib import contextmanager


class Kind(Enum):
    BASE = "b"
    MAYBE = "m"
    TRUTH = "t"
    MATCH = "ma"
    EMPTY = "e"
    UNION = "u"
    PARTITION = "p"
    PARAM = "pa"


_KIND_OF = {k.value: k for k in Kind}
GLOBAL_KINDS = frozenset({Kind.PARAM})
MIB = 2**20


def new_bdd():
    if _bdd.__name__ == "dd.cudd":
        bdd = _bdd.BDD(memory_estimate=16 * MIB, initial_cache_size=2**10)  # type: ignore[call-arg]
        bdd.configure(reordering=True, max_memory=1024 * MIB)
    else:
        bdd = _bdd.BDD()
        bdd.configure(reordering=True)

    return bdd


class Context:
    def __init__(self):
        self.bdd = new_bdd()
        self.true = self.bdd.true
        self.false = self.bdd.false
        self._counter = 0
        self._params: dict[int, str] = {}

    @staticmethod
    def kind(name: VarName) -> Kind:
        return _KIND_OF[name.lstrip("_").rstrip(digits)]

    def fresh(self, kind: Kind) -> Formula:
        var = f"{kind.value}{self._counter}"
        self.bdd.declare(var)
        self._counter += 1
        return self.bdd.var(var)

    def var(self, name: VarName) -> Formula:
        return self.bdd.var(name)

    def sat(self, f: Formula):
        return f != self.false

    def ite(self, g: Formula, u: Formula, v: Formula):
        return self.bdd.ite(g, u, v)

    def all(self, fs: Iterable[Formula]) -> Formula:
        out = self.true
        for f in fs:
            out = out & f
        return out

    def any(self, fs: Iterable[Formula]) -> Formula:
        out = self.false
        for f in fs:
            out = out | f
        return out

    def is_global(self, name: VarName):
        return self.kind(name) in GLOBAL_KINDS

    def param(self, pos: int) -> Formula:
        p = self._params.get(pos)
        if p is None:
            fresh = self.fresh(Kind.PARAM)
            assert fresh.var is not None
            self._params[pos] = p = fresh.var
        return self.var(p)

    @property
    def params(self):
        return {k: self.var(v) for k, v in self._params.items()}

    def declare(self, names: Iterable[str]) -> None:
        bdd = self.bdd
        missing = [n for n in names if n not in bdd.vars]
        if missing:
            bdd.declare(*missing)

    def copy(self, fs: Sequence[Formula], dest: Context):
        """
        copy fs formulas into dest ctx bdd
        """
        with dest.reordering_off() as dest_bdd:
            cp = [self.bdd.copy(f, dest_bdd) for f in fs]
        return cp

    @contextmanager
    def reordering_off(self):
        try:
            self.bdd.configure(reordering=False)
            yield self.bdd
        finally:
            self.bdd.configure(reordering=True)
