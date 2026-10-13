from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Nullability:
    may_null: bool
    may_value: bool

    @property
    def is_bottom(self) -> bool:
        return not (self.may_null or self.may_value)

    def python(self, base: str) -> str:
        if self.is_bottom:
            return "Never"
        if not self.may_value:
            return "None"
        return f"{base} | None" if self.may_null else base

    def __repr__(self) -> str:
        return {(False, False): "⊥", (False, True): "NN", (True, False): "NUL", (True, True): "⊤"}[
            (self.may_null, self.may_value)
        ]


MAYBE_NULL = Nullability(True, True)
