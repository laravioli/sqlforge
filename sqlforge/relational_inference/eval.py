from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from sqlglot import exp

from .context import Context, Formula
from .exception import UnknownColumn
from .relation import Key, Subquery


class ScopeProtocol(Protocol):
    ctx: Context
    side: list[Formula]
    notebook: dict[exp.Expr, Formula]

    def subquery(self, expr: exp.Select | exp.SetOperation, env: Env) -> Subquery: ...


@dataclass(frozen=True, slots=True)
class Env:
    scope: ScopeProtocol
    nulls: Mapping[Key, Formula]
    outer: Env | None

    def evaluator(self):
        return Evaluator(self)

    def bind(self, nulls: Mapping[Key, Formula]):
        return replace(self, nulls=nulls)

    def null(self, key: Key) -> Formula:
        env: Env | None = self
        while env is not None:
            if (formula := env.nulls.get(key)) is not None:
                return formula
            env = env.outer
        raise UnknownColumn(key)


@dataclass(frozen=True, slots=True)
class Evaluator:
    env: Env

    @property
    def ctx(self):
        return self.env.scope.ctx

    @property
    def notebook(self) -> dict[exp.Expr, Formula]:
        return self.env.scope.notebook

    def null(self, e: exp.Expr) -> Formula:
        return self.ctx.true

    def pred(self, e: exp.Expr) -> tuple[Formula, Formula]:
        return (self.ctx.true, self.ctx.true)

    def _subquery(self, expr: exp.Select | exp.SetOperation) -> Subquery:
        sub = self.env.scope.subquery(expr, self.env)
        self.env.scope.side.append((~sub.empty).implies(sub.relation.invariant))
        return sub
