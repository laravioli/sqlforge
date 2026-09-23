from __future__ import annotations

from dataclasses import dataclass
from typing import overload

from sqlglot import exp
from sqlglot.optimizer import Scope, build_scope, optimize
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.simplify import simplify
from sqlglot.schema import MappingSchema

from sqlforge.core.structures import SQL

from .exception import BottomException, SchemaError, StarNotExpanded
from .expression import ExprInference
from .join import JoinInference, JoinNotInferred
from .lattice import CardSet, NullSet
from .structures import Output, meta_set_output


@dataclass(init=False)
class ScopedSQL:
    parent: ScopedSQL | None
    scope: Scope
    user_schema: MappingSchema
    expr_inference: ExprInference
    join_inference: JoinInference
    null_sources: dict[str, Output]

    def __init__(
        self,
        parent: ScopedSQL | None,
        scope: Scope,
        user_schema: MappingSchema,
    ):
        self.parent = parent
        self.scope = scope
        self.user_schema = user_schema
        self.expr_inference = ExprInference(infer_column=self._column_nullability)

        self.join_inference = JoinInference(
            infer_boolean=self.expr_inference.infer_boolean, query=scope.expression
        )
        self.null_sources = {}

        for subquery_scope in self.scope.subquery_scopes:
            meta_set_output(
                subquery_scope.expression,  # type: ignore
                lambda sub_scope=subquery_scope: self._infer_inner_scope(sub_scope),
            )

    @staticmethod
    def root(
        sql: SQL,
        schema: MappingSchema,
        full_optimize=False,
    ):
        expression = sql.expr.copy().unnest()
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
        return ScopedSQL(parent=None, scope=scope, user_schema=schema)

    def _infer_inner_scope(self, scope: Scope):
        return ScopedSQL(parent=self, scope=scope, user_schema=self.user_schema).infer()

    def infer(self) -> Output:
        scope_expression = self.scope.expression

        # resolve set operations
        if self.scope.union_scopes:
            left = self._infer_inner_scope(scope=self.scope.union_scopes[0])
            right = self._infer_inner_scope(scope=self.scope.union_scopes[1])
            return self._infer_set_scope(left, right)

        # resolve ctes and derived tables
        for name, scope in self.scope.sources.items():
            if scope in self.scope.cte_scopes:
                pass
                # TODO: find how to handle recursive then just put the result in null_sources
            if scope in self.scope.derived_table_scopes:
                self.null_sources[name] = self._infer_inner_scope(scope=scope)

        # resolve joins
        try:
            self.join_inference.infer()
        except JoinNotInferred:
            raise NotImplementedError

        # resolve select
        assert isinstance(
            scope_expression, exp.Selectable
        )  # with dml and returning, it should be an if
        return self._infer_select_list(scope_expression.selects)

    def _infer_set_scope(self, left: Output, right: Output):
        match self.scope.expression:
            case exp.Union():
                return Output(
                    [(k1, v1 | v2) for (k1, v1), (_, v2) in zip(left, right, strict=True)],
                    card=left.card | right.card,
                )
            case exp.Intersect():
                # https://github.com/tobymao/sqlglot/issues/8390
                card = None
                output = []
                for (k1, v1), (_, v2) in zip(left, right, strict=True):
                    try:
                        output.append((k1, v1 & v2))
                    except BottomException:
                        output.append((k1, NullSet.MAYBE_NULL))
                        card = CardSet.EMPTY
                return Output(output, card=card or (left.card & right.card))

            case exp.Except():
                return Output(
                    [(k1, v1 - v2) for (k1, v1), (_, v2) in zip(left, right, strict=True)],
                    card=left.card - right.card,
                )
            case _:
                assert False

    def _infer_select_list(self, expressions: list[exp.Expr]) -> Output:
        output: list[tuple[str, NullSet]] = []

        for select in expressions:
            if not select.is_star:
                output.append((select.alias_or_name, self.expr_inference.infer_nullability(select)))
            else:
                match select:
                    case exp.Column(table=table):
                        output.extend(self._star_expand(table))
                    case exp.Star():
                        for source in self.join_inference.ordered_sources:
                            output.extend(self._star_expand(source))
                    case _:
                        # TODO: handle exp.Dot
                        raise StarNotExpanded()

        return Output(output)

    def _star_expand(self, table: str):
        source = self.scope.sources.get(table)
        if source is None:
            if not self.scope.is_correlated_subquery:
                raise StarNotExpanded()
            assert self.parent
            yield from self.parent._star_expand(table)

        pairs = (
            self._schema_nullability(source).items()
            if isinstance(source, exp.Table)
            else self.null_sources[table]
        )
        for name, ns in pairs:
            yield name, self.join_inference.null_extension.get(table, ns)

    def _column_nullability(self, table: str, column: str | None = None) -> NullSet:

        source = self.scope.sources.get(table)

        if source is not None:
            join_extension = self.join_inference.null_extension.get(table)
            if join_extension is not None:
                return join_extension

            if column is None:  # table_column
                return NullSet.NON_NULL

            match source:
                case exp.Table():
                    return self._schema_nullability(source, column)

                case Scope():
                    if source in self.scope.derived_table_scopes:
                        return self.null_sources[table].get(column)
                    return NullSet.MAYBE_NULL

        else:  # external column
            parent = self.parent
            assert parent
            return parent._column_nullability(table, column)

    @overload
    def _schema_nullability(self, table: exp.Table, column: str) -> NullSet: ...
    @overload
    def _schema_nullability(self, table: exp.Table, column: None = None) -> dict[str, NullSet]: ...
    def _schema_nullability(
        self, table: exp.Table, column: str | None = None
    ) -> NullSet | dict[str, NullSet]:
        if column is None:
            schema = {
                name: self._schema_nullability(table, name)
                for name in self.user_schema.column_names(table)
            }
            if len(schema) == 0:
                raise SchemaError()  # this is required for star expansion
            return schema

        dtype = self.user_schema.get_column_type(table, column)
        nullable = dtype.args.get("nullable")
        return NullSet.NON_NULL if nullable is False else NullSet.MAYBE_NULL
