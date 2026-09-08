from enum import StrEnum

from sqlglot import exp


class NullInferenceEngine:
    def __init__(self, schema):
        self.schema = schema

    def infer(self, sql): ...


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


def _is_from_or_join(expression: exp.Expr) -> bool:
    """
    Determine if `expression` is the FROM or JOIN clause of a SELECT statement.
    """
    parent = expression.parent

    # Subqueries can be arbitrarily nested
    while type(parent) is exp.Subquery:
        parent = parent.parent

    return type(parent) in (exp.From, exp.Join)


def _is_derived_table(expression: exp.Expr) -> bool:
    """
    We represent (tbl1 JOIN tbl2) as a Subquery, but it's not really a "derived table",
    as it doesn't introduce a new scope. If an alias is present, it shadows all names
    under the Subquery, so that's one exception to this rule.
    """
    return isinstance(expression, exp.Subquery) and bool(
        expression.alias or isinstance(expression.this, exp.UNWRAPPED_QUERIES)
    )
