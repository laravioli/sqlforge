from sqlglot import exp

from .context import Kind
from .relation import Relation


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


def intersection(left: Relation, right: Relation):
    ctx = left.ctx
    return Relation(
        ctx=ctx,
        columns=left.columns,
        nulls=left.nulls,
        invariant=left.invariant
        & right.invariant
        & ctx.all(l.equiv(r) for l, r in zip(left.nulls, right.nulls, strict=True)),
    )
