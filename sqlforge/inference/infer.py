from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope
from sqlglot.optimizer.simplify import simplify
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL

from .enums import Nullability
from .expression import ExprInference
from .join import JoinInference, JoinNullability


@dataclass(init=False)
class ScopedSQL:
    scope: Scope
    user_schema: MappingSchema
    expr_inference: ExprInference
    join_inference: JoinInference
    join_nullability: JoinNullability | None
    dt_nullability: dict[tuple[int, str], dict[str, Nullability]]

    def __init__(
        self,
        scope: Scope,
        user_schema: MappingSchema,
        dt_nullability: dict[tuple[int, str], dict[str, Nullability]] | None = None,
    ):
        self.scope = scope
        self.user_schema = user_schema
        self.expr_inference = ExprInference(self._get_column_nullability)
        self.join_inference = JoinInference(self.expr_inference.infer_boolean_expression)
        self.join_nullability = None
        self.dt_nullability = dt_nullability or {}

    @staticmethod
    def make(sql: SQL, schema: MappingSchema):
        expression = sql.expr.copy()
        dialect = sql.dialect
        scope = build_scope(
            simplify(
                annotate_types(
                    qualify(expression, schema=schema, dialect=dialect),
                    schema=schema,
                    dialect=dialect,
                ),
                dialect=dialect,
            )
        )
        assert scope is not None, (
            f"build_scope returned None for: {expression.sql()!r} (type={type(expression).__name__})"
        )
        return ScopedSQL(scope=scope, user_schema=schema)

    def replace_scope(self, scope: Scope):
        return ScopedSQL(
            scope=scope,
            user_schema=self.user_schema,
            dt_nullability=self.dt_nullability,
        )

    def infer(self) -> dict[str, Nullability]:
        # resolve derived tables
        for name, scope in self.scope.sources.items():
            if scope in self.scope.derived_table_scopes:
                scoped_sql = self.replace_scope(scope=scope)
                self.dt_nullability[id(self.scope), name] = (
                    scoped_sql.infer()
                )  # check weither scope can be gc'ed
        # resolve joins
        self.join_nullability = self.join_inference.infer(self.scope.expression)
        # resolve select
        output = {}
        for expression in cast(list[exp.Expr], self.scope.expression.expressions):
            output[expression.alias_or_name] = self.expr_inference.infer_nullability(expression)

        return output

    def _get_column_nullability(self, expression: exp.Column) -> Nullability:
        """
        Returns:
                nullability of `col`, use current scope for derived tables and join inference
        """

        if self.join_nullability and self.join_nullability.is_null_extended(expression.table):
            return Nullability.MAYBE_NULL

        source = self.scope.sources.get(expression.table)
        match source:
            case exp.Table():
                dtype = self.user_schema.get_column_type(source, expression.name)
                nullable = dtype.args.get("nullable")
                return Nullability.NON_NULL if nullable is False else Nullability.MAYBE_NULL

            case Scope():
                if source in self.scope.derived_table_scopes:
                    return self.dt_nullability[(id(self.scope), expression.table)][expression.name]
                return Nullability.MAYBE_NULL

            case None:
                # NOTE: it is not clear yet if qualify make this impossible
                raise ValueError()
