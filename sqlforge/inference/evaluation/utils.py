from __future__ import annotations

from collections.abc import Sequence

from sqlglot import exp

from sqlforge.inference.context import Formula
from sqlforge.inference.relation import Col
from sqlforge.inference.structures import Array, Shape

from .structures import Opaque, Scalar, Value
from .syntax import is_empty_value


def to_col(v: Value) -> Col:
    return Col(v.null, v.shape)


def to_value(shape: Shape, null: Formula, key: exp.Expr):
    if shape == "scalar" or isinstance(shape, Array):
        return Scalar(null, key)
    return Opaque(null, shape, key)


def same_shape(options: Sequence[tuple[exp.Expr, Shape]]) -> Shape:
    """CASE, COALESCE, ARRAY[...]: the shape of every option that may give a value"""
    shapes: set[Shape] = {s for x, s in options if not is_empty_value(x)}
    return shapes.pop() if len(shapes) == 1 else "unknown"
