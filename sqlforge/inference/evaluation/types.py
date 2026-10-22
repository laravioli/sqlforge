from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sqlglot import exp

from sqlforge.inference.catalog import Catalog, Composite, PGKey, Shape

if TYPE_CHECKING:
    from .env import Env


def cast_extract(e: exp.Cast) -> PGKey:
    return PGKey((None, ""))


class TypeEval:
    def __init__(self, env: Env, catalog: Catalog):
        self.env = env
        self.catalog = catalog

    def type(self, e: exp.Expr) -> int | Literal["unknown"]:
        """catalog type of a column, field path or cast"""
        match e:
            case exp.Paren(this=this) | exp.Alias(this=this):
                return self.type(this)

            case exp.Column(table=alias, name=col):
                return self.env.col_oid((alias, col))

            case exp.Cast():
                pg_type = self.catalog.pg_type(cast_extract(e))
                return pg_type.oid if pg_type is not None else "unknown"

            case exp.Dot(this=exp.TableColumn() as row, expression=field):  # (t).f is t.f
                return self.env.col_oid((row.name, field.name))

            case exp.Dot(this=base, expression=field):
                match self.shape(base):
                    case Composite(fields=fields):
                        return dict(fields).get(field.name, "unknown")

        return "unknown"

    def shape(self, e: exp.Expr) -> Shape:
        """ask the catalog for a shape : scalar, composite or unknown"""
        oid = self.type(e)
        return "unknown" if oid == "unknown" else self.catalog.shape(oid)
