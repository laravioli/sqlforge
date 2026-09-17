# inspired by:
# Outerjoin Simplication and Reordering
# for Query Optimization
# Cesar A. Galindo-Legaria
# and
# Arnon Rosenthal
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from functools import reduce
from typing import cast

from sqlglot import exp

from .lattice import Boolean, BooleanSet

# Join


class JoinKind(StrEnum):
    CROSS = "CROSS"
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    SEMI = "SEMI"
    ANTI = "ANTI"


def _join_kind(join: exp.Join):
    kind = join.kind
    side = join.side

    if side:
        return JoinKind(side)
    elif kind:
        return JoinKind(kind)
    else:
        is_inner = bool(join.args.get("on") or join.args.get("using") or join.method == "NATURAL")
        return JoinKind.INNER if is_inner else JoinKind.CROSS


def _join_null_extend(join_kind: JoinKind) -> tuple[bool, bool]:
    match join_kind:
        case JoinKind.LEFT:
            return False, True
        case JoinKind.RIGHT:
            return True, False
        case JoinKind.FULL:
            return True, True
        case _:
            return False, False


# Tree


@dataclass
class Predicate:
    expression: exp.Expr
    infer: Callable[[exp.Expr], BooleanSet]
    _reject_cache: dict[frozenset[str], bool] = field(default_factory=dict)

    def null_reject(self, sources: frozenset[str]) -> bool:
        res = self._reject_cache.get(sources)
        if res is None:
            res = self._reject_cache[sources] = self._null_reject_sources(sources)
        return res

    def _null_reject_sources(self, sources: frozenset[str]):
        """
        We say a predicate `p rejects nulls` in attribute set `A` if it evaluates
        to FALSE or UNKNOWN on every tuple in which all attributes in `A` are null
        so consider a null tuple of sources

        Returns:
            True if predicate cannot be True
            False if predicate can be True
        """
        pred = cast(
            exp.Predicate,
            self.expression.transform(
                lambda node: (
                    exp.Null() if (isinstance(node, exp.Column) and node.table in sources) else node
                ),
                copy=True,
            ),
        )
        return Boolean.TRUE not in self.infer(pred).value


@dataclass
class JoinNode:
    kind: JoinKind
    null_extend: tuple[bool, bool]
    left_sources: frozenset[str]
    right_sources: frozenset[str]
    predicate: Predicate | None
    left: TreeNode
    right: TreeNode

    def __post_init__(self):
        assert self.kind != JoinKind.CROSS or self.predicate is None

    def walk(self, exclude_root=False) -> Iterator[TreeNode]:
        stack: list[TreeNode] = [self] if not exclude_root else [self.right, self.left]

        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, JoinNode):
                stack.extend([node.right, node.left])

    def find_all[T](self, *expression_types: type[T], exclude_root: bool = False) -> Iterator[T]:
        for expression in self.walk(exclude_root=exclude_root):
            if isinstance(expression, expression_types):
                yield expression

    def null_reject(self, sources: frozenset[str]) -> bool:
        assert self.predicate is not None
        match self.kind:
            case JoinKind.FULL:
                return False
            case JoinKind.LEFT:
                return sources.issubset(self.right_sources) and self.predicate.null_reject(sources)
            case JoinKind.RIGHT:
                return sources.issubset(self.left_sources) and self.predicate.null_reject(sources)
            case _:
                return self.predicate.null_reject(sources)


@dataclass(frozen=True)
class LeafNode:
    table: exp.Table | exp.Subquery  # subquery in case of derived_table


type TreeNode = LeafNode | JoinNode


def _make_builder(infer_predicate: Callable[[exp.Expr], BooleanSet]):
    def _build_node(expression: exp.Expr) -> TreeNode:

        # get the left side
        left: TreeNode

        match expression:
            case exp.Select():
                from_ = cast(exp.From, expression.args.get("from_"))
                left = _build_node(from_.this)
            case exp.Subquery():
                if bool(expression.alias or isinstance(expression.this, exp.UNWRAPPED_QUERIES)):
                    left = LeafNode(table=expression)
                else:
                    # recurse until we found a table or derived table
                    left = _build_node(expression.this)
            case exp.Table():
                left = LeafNode(table=expression)
            case _:
                raise NotImplementedError()

        # eventually join with the right side
        joins = cast(Iterable[exp.Join] | None, expression.args.get("joins"))
        if not joins:
            return left

        return reduce(
            _lambda_reduce,
            joins,
            left,
        )

    def _lambda_reduce(left: TreeNode, join: exp.Join) -> TreeNode:
        # NOTE: USING and NATURAL are rewritten by sqlglot as ON clause
        on = join.args.get("on")
        kind = _join_kind(join)
        right = _build_node(join.this)

        return JoinNode(
            kind=kind,
            null_extend=_join_null_extend(kind),
            left_sources=_get_join_sources(left),
            right_sources=_get_join_sources(right),
            predicate=Predicate(expression=on, infer=infer_predicate) if on else None,
            left=left,
            right=right,
        )

    return _build_node


def _get_join_sources(node: TreeNode):
    return (
        frozenset({node.table.alias_or_name})
        if isinstance(node, LeafNode)
        else frozenset(node.left_sources | node.right_sources)
    )

    # Simplify


def _simplify_tree(tree: JoinNode) -> None:
    """
    Traverse the tree and transform it in a simplified version,
    wich is equivalent to compute predicate null-effect on the query

    Args:
        tree: join tree computed from a sql ast expression

    Returns:
        None, the tree is modified in place
    """
    for op1 in tree.find_all(JoinNode):
        if op1.kind is not JoinKind.CROSS:
            for op2 in op1.find_all(JoinNode, exclude_root=True):
                match op2.kind:
                    case JoinKind.LEFT:
                        if op1.null_reject(op2.right_sources):
                            op2.kind = JoinKind.INNER
                    case JoinKind.RIGHT:
                        if op1.null_reject(op2.left_sources):
                            op2.kind = JoinKind.INNER

                    case JoinKind.FULL:
                        n1 = op1.null_reject(op2.right_sources)
                        n2 = op1.null_reject(op2.left_sources)

                        if n1 and n2:
                            op2.kind = JoinKind.INNER
                        elif n1:
                            op2.kind = JoinKind.RIGHT
                        elif n2:
                            op2.kind = JoinKind.LEFT
                    case _:
                        continue

                op2.null_extend = _join_null_extend(op2.kind)


# Resolve


@dataclass
class JoinNullability:
    _infered: defaultdict[str, bool]

    def is_null_extended(self, alias_or_name: str):
        return self._infered[alias_or_name]  # could raise KeyError


def _resolve_null_extension(tree: JoinNode):
    null_extensions: dict[str, bool] = defaultdict(lambda: False)

    for node in tree.find_all(JoinNode):
        for table_name in node.left_sources:
            null_extensions[table_name] |= node.null_extend[0]
        for table_name in node.right_sources:
            null_extensions[table_name] |= node.null_extend[1]

    return null_extensions


@dataclass(frozen=True)
class JoinInference:
    infer_predicate: Callable[[exp.Expr], BooleanSet]

    def infer(self, expression: exp.Expr):
        """
        Use outerjoin simplification heuristic to infer joins nullability
        """
        joins = expression.args.get("joins")
        if not joins:
            return None

        builder = _make_builder(self.infer_predicate)
        try:
            tree = cast(JoinNode, builder(expression))
        except NotImplementedError:
            return JoinNullability(_infered=defaultdict(lambda: True))

        _simplify_tree(tree)

        return JoinNullability(_infered=_resolve_null_extension(tree))
