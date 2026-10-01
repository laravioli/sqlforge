from collections.abc import Iterable

from sqlforge.core.structures import QueryKind, TypedSQL
from sqlforge.generator import BodyText, FnParamText, FnReturnText, FnText, Text


class APGFnGenerator:
    def __init__(self, sqls: list[TypedSQL], schema_module: str | None = None):
        self.sqls = sqls
        self.schema_module = schema_module

    def generate(self):
        txt = (
            Text("from __future__ import annotations")
            .newline()
            .newline()
            .import_("asyncpg")
            .import_("datetime")
            .import_("decimal")
            .import_("ipaddress")
            .import_("msgspec")
            .import_("typing")
            .import_("uuid")
            .newline()
            .import_from("collections.abc", "Iterable")
        )
        if self.schema_module:
            txt.add(f"from {self.schema_module} import *  # noqa: F403\n")
        txt.newline()
        for fn in self._fn_writer():
            txt.add(fn).newline()

        return txt

    def _fn_writer(self):
        for sql in self.sqls:
            txt = (
                Text(f'{sql.source.name.upper()} : typing.Final[str] = """{sql.source!s}"""')
                .newline()
                .newline()
            )

            match sql.source.kind:
                case QueryKind.ONE:
                    txt.add(self._one(sql))
                case QueryKind.MANY:
                    txt.add(self._many(sql))
                case QueryKind.FETCHVAL:
                    txt.add(self._fetchval(sql))
                case QueryKind.FETCHMANY:
                    txt.add(self._fetchmany(sql))
                case QueryKind.EXEC:
                    txt.add(self._exec(sql))
                case QueryKind.EXECMANY:
                    txt.add(self._execmany(sql))
            yield txt

    def _build_fn_params(self, sql: TypedSQL, *, many=False, record_class=True):
        params = FnParamText("conn", "asyncpg.Connection")
        if many:
            params.add_param("args", f"Iterable[{_row(sql.typed_params.values())}]").asterix()
        else:
            for name, type_ in sql.typed_params.items():
                params.add_param(name, type_)
        params.add_param("timeout", "float | None", "None")
        if record_class:
            # the argument is a class, not a record
            params.add_param("record_class", "type[asyncpg.Record] | None", "None")
        return params

    def _one(self, sql: TypedSQL):
        params = self._build_fn_params(sql)
        body = BodyText(_call("fetchrow", sql, "timeout=timeout", "record_class=record_class"))
        return_ = FnReturnText().add(f"{_row(sql.typed_attrs.values())} | None")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _many(self, sql: TypedSQL):
        params = self._build_fn_params(sql)
        body = BodyText(_call("fetch", sql, "timeout=timeout", "record_class=record_class"))
        return_ = FnReturnText().add(f"list[{_row(sql.typed_attrs.values())}]")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _fetchval(self, sql: TypedSQL):
        columns = ", ".join(str(n) for n in range(max(len(sql.typed_attrs), 1)))
        params = self._build_fn_params(sql, record_class=False).add_param(
            "column", f"typing.Literal[{columns}]", "0"
        )
        body = BodyText(_call("fetchval", sql, "column=column", "timeout=timeout"))
        values = list(dict.fromkeys(sql.typed_attrs.values()))  # distinct types, in column order
        return_ = FnReturnText().add(" | ".join([*values, "None"]))
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _fetchmany(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=True)
        body = BodyText(
            f"return await conn.fetchmany({sql.source.name.upper()}, args, timeout=timeout, record_class=record_class)"
        )
        return_ = FnReturnText().add(f"list[{_row(sql.typed_attrs.values())}]")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _exec(self, sql: TypedSQL):
        params = self._build_fn_params(sql, record_class=False)
        body = BodyText(_call("execute", sql, "timeout=timeout"))
        return_ = FnReturnText().add("str")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _execmany(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=True, record_class=False)
        body = BodyText(
            f"return await conn.executemany({sql.source.name.upper()}, args, timeout=timeout)"
        )
        return_ = FnReturnText().add("None")
        return FnText(sql.source.name.lower(), params, body, return_).gen()


def _row(types: Iterable[str]) -> str:
    types = list(types)
    return f"tuple[{', '.join(types)}]" if types else "tuple[()]"


def _call(method: str, sql: TypedSQL, *extra: str) -> str:
    args = [sql.source.name.upper(), *sql.typed_params.keys(), *extra]
    return f"return await conn.{method}({', '.join(args)})"
