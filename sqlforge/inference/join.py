# inspired by:
# Outerjoin Simplication and Reordering
# for Query Optimization
# Cesar A. Galindo-Legaria
# and
# Arnon Rosenthal
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce
from typing import cast

from sqlglot import exp

from .exception import JoinNotInferred, NoFromClause
from .lattice import BooleanSet, NullSet

# Join

type JoinModifier = dict[str, NullSet]


class JoinKind(StrEnum):
    CROSS = "CROSS"
    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"

    @staticmethod
    def from_expr(join: exp.Join):
        kind = join.kind
        side = join.side

        if side:
            return JoinKind(side)
        elif kind:
            return JoinKind(kind)
        else:
            is_inner = bool(
                join.args.get("on") or join.args.get("using") or join.method == "NATURAL"
            )
            return JoinKind.INNER if is_inner else JoinKind.CROSS


# Tree


@dataclass(frozen=True)
class Predicate:
    _infer: Callable[[exp.Expr, frozenset[str]], BooleanSet]
    expression: exp.Predicate | exp.Connector | exp.Boolean | exp.Not

    def null_reject(self, sources: frozenset[str]):
        """
        We say a predicate `p rejects nulls` in attribute set `A` if it evaluates
        to FALSE or UNKNOWN on every tuple in which all attributes in `A` are null
        so consider a null tuple of sources

        Parameters:
                join_modifier: mapping to determine null tuples and current join null-extension

        Returns:
            True if predicate cannot be True
            False if predicate can be True
        """
        return not self._infer(self.expression, sources).can_be_true


@dataclass(init=False)
class JoinNode:
    kind: JoinKind  # mutable
    left: TreeNode
    right: TreeNode
    left_sources: frozenset[str]
    right_sources: frozenset[str]
    predicate: Predicate | None

    def __init__(
        self,
        kind: JoinKind,
        left: TreeNode,
        right: TreeNode,
        left_sources: frozenset[str],
        right_sources: frozenset[str],
        expression: exp.Expr | None,
        set_modifier: Callable[[dict[str, NullSet]], None],
        infer: Callable[[exp.Expr], BooleanSet],
    ):
        self.kind = kind
        self.left = left
        self.right = right
        self.left_sources = left_sources
        self.right_sources = right_sources

        if expression is None:
            self.predicate = None
        else:
            assert self.kind != JoinKind.CROSS
            assert isinstance(expression, exp.Predicate | exp.Connector | exp.Boolean | exp.Not)

            def infer_boolean(predicate: exp.Expr, sources: frozenset[str]):
                set_modifier(
                    self.resolve_null_extension(exclude_self=True)
                    | {k: NullSet.NULL for k in sources}
                )
                return infer(predicate)

            self.predicate = Predicate(_infer=infer_boolean, expression=expression)

    @property
    def null_extend(self):
        match self.kind:
            case JoinKind.LEFT:
                return False, True
            case JoinKind.RIGHT:
                return True, False
            case JoinKind.FULL:
                return True, True
            case _:
                return False, False

    def walk(self, exclude_self: bool = False) -> Iterator[TreeNode]:
        stack: list[TreeNode] = [self] if not exclude_self else [self.right, self.left]

        while stack:
            node = stack.pop()
            yield node
            if isinstance(node, JoinNode):
                stack.extend([node.right, node.left])

    def find_all[T](self, *expression_types: type[T], exclude_self: bool = False) -> Iterator[T]:
        for expression in self.walk(exclude_self=exclude_self):
            if isinstance(expression, expression_types):
                yield expression

    def null_reject(self, sources: frozenset[str]) -> bool:
        """Test operator null-rejection on attribute set `sources`"""
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

    def resolve_null_extension(self: JoinNode, exclude_self=False) -> JoinModifier:
        """
        Does sources (user_table and derived table)
        from left and right side are null-extended ?
        Returns:
            Mapping `source_name` -> `null-extended`
        """
        null_extensions: dict[str, bool] = {}

        for node in self.find_all(JoinNode, exclude_self=exclude_self):
            for t in node.left_sources:
                null_extensions[t] = null_extensions.get(t, False) or node.null_extend[0]
            for t in node.right_sources:
                null_extensions[t] = null_extensions.get(t, False) or node.null_extend[1]

        return {k: NullSet.MAYBE_NULL for k, v in null_extensions.items() if v}


@dataclass(frozen=True)
class LeafNode:
    source: exp.Table | exp.Subquery  # subquery in case of derived_table


type TreeNode = LeafNode | JoinNode


def _make_builder(
    infer_boolean: Callable[[exp.Expr], BooleanSet],
    set_modifier: Callable[[dict[str, NullSet]], None],
):
    def _build_node(expression: exp.Expr) -> TreeNode:

        # get the left side
        left: TreeNode

        match expression:
            case exp.Select():
                from_ = cast(exp.From | None, expression.args.get("from_"))
                if from_ is None:
                    raise NoFromClause()
                left = _build_node(from_.this)
            case exp.Table():
                left = LeafNode(source=expression)
            case exp.Subquery():
                if bool(
                    expression.alias or isinstance(expression.this, exp.UNWRAPPED_QUERIES)
                ):  # derived_table
                    left = LeafNode(source=expression)
                else:
                    # recurse until we found a table or derived table
                    left = _build_node(expression.this)
            case exp.Lateral():
                raise JoinNotInferred
            case _:
                # udtf
                raise JoinNotInferred

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
        kind = JoinKind.from_expr(join)
        right = _build_node(join.this)

        return JoinNode(
            kind=kind,
            left=left,
            right=right,
            left_sources=_get_join_sources(left),
            right_sources=_get_join_sources(right),
            expression=on,
            infer=infer_boolean,
            set_modifier=set_modifier,
        )

    return _build_node


def _get_join_sources(node: TreeNode):
    return (
        frozenset({node.source.alias_or_name})
        if isinstance(node, LeafNode)
        else frozenset(node.left_sources | node.right_sources)
    )


# Simplify


def _simplify_tree(tree: JoinNode) -> bool:
    """
    Traverse the tree and transform it in a simplified version,
    wich is equivalent to compute predicate null-effect on the query

    Args:
        tree: join tree computed from a sql ast expression

    Returns:
        `True` if at least one join kind was changed else `False`
    """
    modified = False

    for op1 in tree.find_all(JoinNode):
        if op1.kind is JoinKind.CROSS:
            continue
        for op2 in op1.find_all(JoinNode, exclude_self=True):
            match op2.kind:
                case JoinKind.LEFT:
                    if op1.null_reject(op2.right_sources):
                        modified = True
                        op2.kind = JoinKind.INNER
                case JoinKind.RIGHT:
                    if op1.null_reject(op2.left_sources):
                        modified = True
                        op2.kind = JoinKind.INNER

                case JoinKind.FULL:
                    n1 = op1.null_reject(op2.right_sources)
                    n2 = op1.null_reject(op2.left_sources)

                    if n1 or n2:
                        modified = True
                        if n1 and n2:
                            op2.kind = JoinKind.INNER
                        elif n1:
                            op2.kind = JoinKind.RIGHT
                        else:
                            op2.kind = JoinKind.LEFT

    return modified


# Resolve


class JoinInference:
    def __init__(self, infer_boolean: Callable[[exp.Expr], BooleanSet], expression: exp.Expr):
        self._modifier: JoinModifier = {}

        from_clause = cast(exp.From | None, expression.args.get("from_"))
        if from_clause:
            self._tree = _make_builder(infer_boolean, self._set_modifier)(expression)
            match self._tree:
                case LeafNode():
                    self.ordered_sources = [self._tree.source.alias_or_name]
                case JoinNode():
                    self.ordered_sources = [
                        n.source.alias_or_name for n in self._tree.walk() if isinstance(n, LeafNode)
                    ]
        else:
            self._tree = None
            self.ordered_sources = []

    @property
    def null_extension(self):
        return self._modifier

    def _set_modifier(self, modif: JoinModifier):
        # A dangerous part of the design.
        # This allow the resolution of on clause
        # using the simplification algorithm
        self._modifier = modif

    def infer(self) -> None:
        """
        Use outerjoin simplification heuristic to infer joins nullability.
        """
        if isinstance(self._tree, JoinNode):
            while _simplify_tree(self._tree):  # fixed-point
                pass
            self._modifier = self._tree.resolve_null_extension()
