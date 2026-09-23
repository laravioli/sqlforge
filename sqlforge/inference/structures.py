from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlglot import exp

from .lattice import CardSet, NullSet


@dataclass(frozen=True)
class Output:
    """
    Output representation of a select expression.
    Always star expanded with order preserved
    """

    _output: Sequence[tuple[str, NullSet]]
    card: CardSet = CardSet.TOP

    def __iter__(self):
        return iter(self._output)

    @property
    def columns(self):
        return (t[0] for t in self._output)

    @property
    def nulls(self):
        return (t[1] for t in self._output)

    def get(self, col: int | str, default: NullSet = NullSet.MAYBE_NULL) -> NullSet:
        """
        Returns:
            Nullset of first tuple matched else default
        """
        if isinstance(col, int):
            return self._output[col][1]
        for t in self._output:
            if t[0] == col:
                return t[1]
        return default

    def unwrap(self):
        return self._output


def meta_get_output(expression: exp.Select | exp.SetOperation) -> Output:
    # lazy because output fn is context dependant
    output: Callable[[], Output] | None = expression.meta_get("sqlforge_output_fn")
    assert output is not None
    return output()


def meta_set_output(
    expression: exp.Select | exp.SetOperation, output: Callable[[], Output]
) -> None:
    expression.meta["sqlforge_output_fn"] = output
