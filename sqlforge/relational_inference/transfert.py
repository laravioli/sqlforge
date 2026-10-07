from __future__ import annotations

from enum import StrEnum

from sqlglot import exp

from .context import Context, Formula, Kind
from .exception import Unsupported
from .relation import Relation, Row


def setop(node: exp.SetOperation, left: Relation, right: Relation) -> Relation:
    match node:
        case exp.Union():
            return union(left, right)
        case exp.Intersect():
            return intersection(left, right)
        case exp.Except():
            return left
        case _:
            assert False


def union(left: Relation, right: Relation) -> Relation:

    ctx = left.ctx
    side = ctx.fresh(Kind.UNION)
    return Relation(
        ctx=left.ctx,
        columns=left.columns,
        nulls=[(side & l) | (~side & r) for l, r in zip(left.nulls, right.nulls, strict=True)],
        invariant=(side.implies(left.invariant) & (~side).implies(right.invariant)),
    )


def intersection(left: Relation, right: Relation) -> Relation:
    ctx = left.ctx
    return Relation(
        ctx=ctx,
        columns=left.columns,
        nulls=left.nulls,
        invariant=left.invariant
        & right.invariant
        & ctx.all(l.equiv(r) for l, r in zip(left.nulls, right.nulls, strict=True)),
    )


def filter_(row: Row, on: Formula) -> Row:
    return Row(nulls=row.nulls, invariant=row.invariant & on)


class JoinKind(StrEnum):
    COMMA = "COMMA"
    CROSS = "CROSS"
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"

    @staticmethod
    def from_expr(join: exp.Join) -> JoinKind:
        side, kind, on = join.side, join.kind, join.args.get("on")
        if side in ("LEFT", "RIGHT", "FULL") and kind in ("", "OUTER"):
            return JoinKind(side)
        if not side and kind == "CROSS":
            return JoinKind.CROSS
        if not side and kind in ("", "INNER"):
            if on is not None:
                return JoinKind.INNER
            return JoinKind.COMMA if not kind else JoinKind.CROSS
        raise Unsupported(f"{side} {kind} JOIN")  # SEMI, ANTI, … are not Postgres


def cross(left: Row, right: Row) -> Row:
    return Row(nulls={**left.nulls, **right.nulls}, invariant=left.invariant & right.invariant)


def _pad(row: Row, real: Formula) -> Row:
    return Row({k: real.implies(n) for k, n in row.nulls.items()}, real.implies(row.invariant))


def join(ctx: Context, kind: JoinKind, left: Row, right: Row, on: Formula) -> Row:
    ml = ctx.fresh(Kind.MATCH) if kind in (JoinKind.RIGHT, JoinKind.FULL) else ctx.true
    mr = ctx.fresh(Kind.MATCH) if kind in (JoinKind.LEFT, JoinKind.FULL) else ctx.true
    return filter_(cross(_pad(left, ml), _pad(right, mr)), (ml | mr) & (ml & mr).implies(on))
