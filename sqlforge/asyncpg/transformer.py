from sqlglot import exp

from sqlforge.data import SQL, TransformedSQL


def transform(sqls: list[SQL]) -> list[TransformedSQL]:
    return [_transform_one(sql) for sql in sqls]


def _transform_one(sql: "SQL") -> TransformedSQL:
    params: dict[str, int] = {}
    param_nb = 1
    placeholders = sql.expr.find_all(exp.Placeholder)

    for p in placeholders:
        if p.name not in params:
            params[p.name] = param_nb
            param_nb += 1
        p.replace(
            exp.Parameter(
                this=exp.Literal(
                    this=str(params[p.name]),
                    is_string=False,
                )
            )
        )
    return TransformedSQL(
        **sql.to_dict(),
        params=params,
    )
