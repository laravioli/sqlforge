# from collections.abc import Callable
# from dataclasses import dataclass, field

# from sqlglot import exp
# from sqlglot.optimizer import find_all_in_scope

# from .join import JoinKind, JoinNode
# from .lattice import BooleanSet, NullSet

# type WhereModifier = dict[tuple[str, str], NullSet]


# @dataclass
# class WhereInference:
#     _infer_boolean: Callable[[exp.Expr], BooleanSet]
#     _modifier: WhereModifier = field(default_factory=dict)

#     def get(self, table: str, column: str):
#         return self._modifier.get((table, column))

#     def infer(self, tree: JoinNode):
#         predicate = _build_predicate(tree)
#         columns = _columns(predicate)
#         for c in columns:
#             nullability = self._infer_boolean()


# def _build_predicate(tree: JoinNode):
#     return exp.and_(
#         *(
#             node.predicate.expression
#             for node in tree.find_all(JoinNode)
#             if node.kind is JoinKind.INNER and node.predicate is not None
#         )
#     )


# def _columns(expression: exp.Expr):
#     columns: set[tuple[str, str]] = set()
#     for c in find_all_in_scope(expression, exp.Column):
#         table, column = c.table, c.name
#         columns.add((table, column))

#     return columns
