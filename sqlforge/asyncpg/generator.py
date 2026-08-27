from sqlforge.datastruct import QueryKind, TypedSQL
from sqlforge.generator import BodyText, FnParamText, FnReturnText, FnText, Text


class APGFnGenerator:
    def __init__(self, sqls: list[TypedSQL]):
        self.sqls = sqls

    def generate(self):
        txt = (
            Text("")
            .import_("asyncpg")
            .import_("datetime")
            .import_("decimal")
            .import_("ipaddress")
            .import_("msgspec")
            .import_("typing")
            .import_("uuid")
            .newline()
        )
        for fn in self._fn_writer():
            txt.add(fn).newline()

        return txt

    def _fn_writer(self):
        for sql in self.sqls:
            txt = (
                Text(f'{sql.source.name.upper()} : typing.Final[str] = """{sql!s}"""')
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
        match many:
            case False:
                for p in sql.typed_params.items():
                    params.add_param(p[0], p[1])
            case True:
                params.add_param(
                    "args", f"Iterable[tuple[{','.join(a for a in sql.typed_params.values())}]]"
                ).asterix()
        params.add_param("timeout", "float | None", "None")
        if record_class:
            params.add_param("record_class", "asyncpg.Record | None", "None")
        return params

    def _one(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=False, record_class=True)
        body = BodyText(
            f"return await conn.fetchrow({sql.source.name.upper()}, {', '.join(sql.typed_params.keys())}, timeout=timeout, record_class=record_class)"
        )
        return_ = FnReturnText().add(f"tuple[{','.join(a for a in sql.typed_attrs.values())}]")

        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _many(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=False, record_class=True)
        body = BodyText(
            f"return await conn.fetch({sql.source.name.upper()}, {', '.join(sql.typed_params.keys())}, timeout=timeout, record_class=record_class)"
        )
        return_ = FnReturnText().add(
            f"list[tuple[{','.join(a for a in sql.typed_attrs.values())}]]"
        )

        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _fetchval(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=False, record_class=False).add_param(
            "column", f"Literal[{','.join(str(n) for n in range(len(sql.typed_attrs)))}]", "0"
        )
        body = (
            BodyText(
                f"data : {f'tuple[{",".join(sql.typed_attrs.values())}]'} = await conn.fetchrow({sql.source.name.upper()}, {', '.join(sql.typed_params.keys())}, timeout=timeout)"
            )
            .add_statement("if not data:")
            .add_statement(Text("").indent().add("return None"))
            .add_statement("return data[column]")
        )

        return FnText(sql.source.name.lower(), params, body).gen()

    def _fetchmany(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=True, record_class=True)
        body = BodyText(
            f"return await conn.fetchmany({sql.source.name.upper()}, args, timeout=timeout, record_class=record_class)"
        )
        return_ = FnReturnText().add(
            f"list[tuple[{','.join(a for a in sql.typed_attrs.values())}]]"
        )
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _exec(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=False, record_class=False)
        body = BodyText(
            f"return await conn.execute({sql.source.name.upper()}, {', '.join(sql.typed_params.keys())}, timeout=timeout)"
        )
        return_ = FnReturnText().add("str")

        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _execmany(self, sql: TypedSQL):
        params = self._build_fn_params(sql, many=True, record_class=False)
        body = BodyText(
            f"return await conn.executemany({sql.source.name.upper()}, args, timeout=timeout)"
        )
        return_ = FnReturnText().add("None")

        return FnText(sql.source.name.lower(), params, body, return_).gen()
