from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from functools import reduce
from typing import cast

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

# Join


class JoinKind(StrEnum):
    CROSS = "CROSS"
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    SEMI = "SEMI"
    ANTI = "ANTI"


def join_kind(join: exp.Join):
    kind = join.kind
    side = join.side

    if side:
        return JoinKind(side)
    elif kind:
        return JoinKind(kind)
    else:
        is_inner = bool(join.args.get("on") or join.args.get("using") or join.method == "NATURAL")
        return JoinKind.INNER if is_inner else JoinKind.CROSS


def join_null_extend(join_kind: JoinKind) -> tuple[bool, bool]:
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
    _reject_cache: dict[frozenset[str], bool] = field(default_factory=dict)

    def null_reject(self, sources: frozenset[str]) -> bool:
        res = self._reject_cache.get(sources)
        if res is None:
            res = self._reject_cache[sources] = self._resolve_null_reject(sources)
        return res

    def _resolve_null_reject(self, sources: frozenset[str]):
        # NOTE its enough to reject on any element in sources
        return True


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


def build_node(expression: exp.Expr) -> TreeNode:

    # get the left side
    left: TreeNode

    match expression:
        case exp.Select():
            from_ = cast(exp.From | None, expression.args.get("from_"))
            if not from_:
                raise ValueError("there is no join to infer")
            left = build_node(from_.this)
        case exp.Subquery():
            if bool(expression.alias or isinstance(expression.this, exp.UNWRAPPED_QUERIES)):
                left = LeafNode(table=expression)  # for now we assume the dt is resolved
            else:
                # recurse until we found a table or derived table
                left = build_node(expression.this)
        case exp.Table():
            left = LeafNode(table=expression)
        case _:
            raise ValueError("unhandled case")

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

    on = join.args.get("on")
    kind = join_kind(join)
    right = build_node(join.this)

    return JoinNode(
        kind=kind,
        null_extend=join_null_extend(kind),
        left_sources=_get_join_sources(left),
        right_sources=_get_join_sources(right),
        predicate=Predicate(on) if on else None,
        left=left,
        right=right,
    )


def _get_join_sources(node: TreeNode):
    return (
        frozenset({node.table.alias_or_name})
        if isinstance(node, LeafNode)
        else frozenset(node.left_sources | node.right_sources)
    )

    # Simplify


def simplify(tree: JoinNode) -> None:
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

                op2.null_extend = join_null_extend(op2.kind)


# Resolve


@dataclass
class JoinInference:
    _infered: defaultdict[str, bool]

    def is_null_extended(self, alias_or_name: str):
        return self._infered[alias_or_name]  # could raise KeyError


def resolve_null_extension(tree: JoinNode):
    null_extensions: dict[str, bool] = defaultdict(lambda: False)

    for node in tree.find_all(JoinNode):
        for table_name in node.left_sources:
            null_extensions[table_name] |= node.null_extend[0]
        for table_name in node.right_sources:
            null_extensions[table_name] |= node.null_extend[1]

    return null_extensions


def infer_joins(scope: Scope):
    # TODO write shortcut logic
    tree = cast(JoinNode, build_node(scope.expression))
    simplify(tree)
    return JoinInference(_infered=resolve_null_extension(tree))


# NOTE first phase: shortcut -> should i bypass the whole thing and how ?
# (for exemple check if there is top level lateral, if there is a from clause, if there is join even)
# should use a scoped version probably
# NOTE second phase (optional) -> do the whole inference
