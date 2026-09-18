from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlglot import exp
from sqlglot.optimizer import optimize
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope
from sqlglot.optimizer.simplify import simplify
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL

from .expression import ExprInference
from .join import JoinInference, JoinNullability
from .lattice import NullSet


# TODO : chain of union/intersect/except(use | & -, columns wise, in the correct order) then ctes
@dataclass(init=False)
class ScopedSQL:
    scope: Scope
    user_schema: MappingSchema
    expr_inference: ExprInference
    join_inference: JoinInference
    join_nullability: JoinNullability | None
    dt_nullability: dict[tuple[int, str], dict[str, NullSet]]  # shared

    def __init__(
        self,
        scope: Scope,
        user_schema: MappingSchema,
        dt_nullability: dict[tuple[int, str], dict[str, NullSet]] | None = None,
    ):
        self.scope = scope
        self.user_schema = user_schema
        self.expr_inference = ExprInference(
            self._get_column_nullability, self._get_table_column_nullability
        )
        self.join_inference = JoinInference(self.expr_inference.infer_boolean_expr)
        self.join_nullability = None
        self.dt_nullability = dt_nullability or {}

    @staticmethod
    def root(sql: SQL, schema: MappingSchema, full_optimize=False):
        expression = sql.expr.copy().unnest()
        # NOTE: maybe root should not make it (None) when i dont infer
        # NOTE: i need somewhere, where i decide ok i dont need/have to infer this
        dialect = sql.dialect
        ast = (
            optimize(expression, schema=schema, dialect=dialect)
            if full_optimize
            else simplify(
                annotate_types(
                    qualify(expression, schema=schema, dialect=dialect),
                    schema=schema,
                    dialect=dialect,
                ),
                dialect=dialect,
            )
        )
        scope = build_scope(ast)
        assert scope is not None, (
            f"build_scope returned None for: {expression.sql()!r} (type={type(expression).__name__})"
        )
        return ScopedSQL(scope=scope, user_schema=schema)

    def infer_inner_scope(self, scope: Scope):
        """
        Enter a new, inner scope using a copy of `ScopedSQL`(sharing user-schema and derived-table inference)
        then infer the scoped expression
        """
        return ScopedSQL(
            scope=scope,
            user_schema=self.user_schema,  # read-only
            dt_nullability=self.dt_nullability,  # mutable
        ).infer()

    def infer(self) -> dict[str, NullSet]:
        """
        main, recursive, nullability inference algorithm
        """
        current_expr = self.scope.expression

        # resolve set operations
        if isinstance(current_expr, exp.SetOperation):
            l_out = self.infer_inner_scope(scope=self.scope.union_scopes[0])
            r_out = self.infer_inner_scope(scope=self.scope.union_scopes[1])
            match current_expr:
                case exp.Union():
                    return {k1: v1 | v2 for (k1, v1), (_, v2) in zip(l_out.items(), r_out.items())}
                case exp.Intersect():
                    # https://github.com/tobymao/sqlglot/issues/8390
                    return {k1: v1 & v2 for (k1, v1), (_, v2) in zip(l_out.items(), r_out.items())}
                case exp.Except():
                    return {k1: v1 - v2 for (k1, v1), (_, v2) in zip(l_out.items(), r_out.items())}

        # resolve derived tables
        for name, scope in self.scope.sources.items():
            if scope in self.scope.derived_table_scopes:
                self.dt_nullability[id(self.scope), name] = self.infer_inner_scope(scope=scope)

        # resolve joins
        self.join_nullability = self.join_inference.infer(current_expr)

        # resolve select
        return {
            e.alias_or_name: self.expr_inference.infer_nullability(e)
            for e in cast(list[exp.Expr], current_expr.expressions)
        }

    def _get_column_nullability(self, expression: exp.Column) -> NullSet:
        """
        Given a scope, use user-table and derived table sources result.
        Join results modify the nullability after join inference.
        Returns:
                nullability of `col`
        """

        table = expression.table

        if self.join_nullability and self.join_nullability.is_null_extended(table):
            return NullSet.MAYBE_NULL

        source = self.scope.sources.get(table)
        match source:
            case exp.Table():
                dtype = self.user_schema.get_column_type(source, expression.name)
                nullable = dtype.args.get("nullable")
                return NullSet.NON_NULL if nullable is False else NullSet.MAYBE_NULL

            case Scope():
                if source in self.scope.derived_table_scopes:
                    return self.dt_nullability[(id(self.scope), table)][expression.name]
                return NullSet.MAYBE_NULL

            case None:
                # NOTE: it is not clear yet if qualify make this impossible
                raise ValueError()

    def _get_table_column_nullability(self, expression: exp.TableColumn) -> NullSet:
        assert self.join_nullability is not None
        if self.join_nullability.is_null_extended(expression.name):
            return NullSet.MAYBE_NULL
        return NullSet.NON_NULL
