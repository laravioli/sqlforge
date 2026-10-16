from collections.abc import Iterable

from sqlforge.core.structures import QueryKind
from sqlforge.generator import BodyText, FnParamText, FnReturnText, FnText, Text
from sqlforge.inference import AnalyzedSQL


class APGFnGenerator:
    def __init__(self, sqls: list[AnalyzedSQL], schema_module: str | None = None):
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
            .import_from("enum", "StrEnum")
            .import_from("msgspec", "Struct")
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

    def _build_fn_params(self, sql: AnalyzedSQL, *, many=False, record_class=True):
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

    def _one(self, sql: AnalyzedSQL):
        """Run a query and return the first row.

        :param str query:
            Query text
        :param args:
            Query arguments
        :param float timeout:
            Optional timeout value in seconds.
        :param type record_class:
            If specified, the class to use for the value returned by this
            method.  Must be a subclass of :class:`~asyncpg.Record`.
            If not specified, a per-connection *record_class* is used.

        :return:
            The first row as a :class:`~asyncpg.Record` instance, or None if
            no records were returned by the query.  If specified,
            *record_class* is used as the type for the result value.
        """

        params = self._build_fn_params(sql)
        body = BodyText(_call("fetchrow", sql, "timeout=timeout", "record_class=record_class"))
        return_ = FnReturnText().add(f"{_row(t[1] for t in sql.typed_attrs)} | None")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _many(self, sql: AnalyzedSQL):
        """Run a query and return the results as a list of :class:`Record`.

        :param str query:
            Query text.
        :param args:
            Query arguments.
        :param float timeout:
            Optional timeout value in seconds.
        :param type record_class:
            If specified, the class to use for records returned by this method.
            Must be a subclass of :class:`~asyncpg.Record`.  If not specified,
            a per-connection *record_class* is used.

        :return list:
            A list of :class:`~asyncpg.Record` instances.  If specified, the
            actual type of list elements would be *record_class*.
        """
        params = self._build_fn_params(sql)
        body = BodyText(_call("fetch", sql, "timeout=timeout", "record_class=record_class"))
        return_ = FnReturnText().add(f"list[{_row(t[1] for t in sql.typed_attrs)}]")
        return FnText(sql.name.lower(), params, body, return_).gen()

    def _fetchval(self, sql: AnalyzedSQL):
        """Run a query and return a value in the first row.

        :param str query: Query text.
        :param args: Query arguments.
        :param int column: Numeric index within the record of the value to
                           return (defaults to 0).
        :param float timeout: Optional timeout value in seconds.
                            If not specified, defaults to the value of
                            ``command_timeout`` argument to the ``Connection``
                            instance constructor.

        :return: The value of the specified column of the first record, or
                 None if no records were returned by the query.
        """
        columns = ", ".join(str(n) for n in range(max(len(sql.typed_attrs), 1)))
        params = self._build_fn_params(sql, record_class=False).add_param(
            "column", f"typing.Literal[{columns}]", "0"
        )
        body = BodyText(_call("fetchval", sql, "column=column", "timeout=timeout"))
        values = list(
            dict.fromkeys(t[1] for t in sql.typed_attrs)
        )  # distinct types, in column order
        return_ = FnReturnText().add(" | ".join([*values, "None"]))
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _fetchmany(self, sql: AnalyzedSQL):
        """Run a query for each sequence of arguments in *args*
        and return the results as a list of :class:`Record`.

        :param query:
            Query to execute.
        :param args:
            An iterable containing sequences of arguments for the query.
        :param float timeout:
            Optional timeout value in seconds.
        :param type record_class:
            If specified, the class to use for records returned by this method.
            Must be a subclass of :class:`~asyncpg.Record`.  If not specified,
            a per-connection *record_class* is used.

        :return list:
            A list of :class:`~asyncpg.Record` instances.  If specified, the
            actual type of list elements would be *record_class*.

        Example:

        .. code-block:: pycon

            >>> rows = await con.fetchmany('''
            ...         INSERT INTO mytab (a, b) VALUES ($1, $2) RETURNING a;
            ...     ''', [('x', 1), ('y', 2), ('z', 3)])
            >>> rows
            [<Record row=('x',)>, <Record row=('y',)>, <Record row=('z',)>]
        """
        params = self._build_fn_params(sql, many=True)
        body = BodyText(
            f"return await conn.fetchmany({sql.source.name.upper()}, args, timeout=timeout, record_class=record_class)"
        )
        return_ = FnReturnText().add(f"list[{_row(t[1] for t in sql.typed_attrs)}]")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _exec(self, sql: AnalyzedSQL):
        """Execute an SQL command (or commands).

        This method can execute many SQL commands at once, when no arguments
        are provided.

        Example:

        .. code-block:: pycon

            >>> await con.execute('''
            ...     CREATE TABLE mytab (a int);
            ...     INSERT INTO mytab (a) VALUES (100), (200), (300);
            ... ''')
            INSERT 0 3

            >>> await con.execute('''
            ...     INSERT INTO mytab (a) VALUES ($1), ($2)
            ... ''', 10, 20)
            INSERT 0 2

        :param args: Query arguments.
        :param float timeout: Optional timeout value in seconds.
        :return str: Status of the last SQL command.

        When query arguments are provided, the command is executed as a
        prepared statement and is eligible for the connection's LRU
        statement cache.

        The status string for an ``INSERT`` has the form
        ``INSERT <oid> <count>``.  A result such as ``INSERT 0 0`` is a
        legitimate outcome for queries that insert zero rows (for example,
        ``INSERT ... SELECT ... WHERE false``), and does not indicate a
        failure.  To confirm that a single row was inserted, check the
        status string:

        .. code-block:: pycon

            >>> result = await con.execute(
            ...     'INSERT INTO mytab (a) VALUES ($1)', 1)
            >>> assert result == 'INSERT 0 1'
        """
        params = self._build_fn_params(sql, record_class=False)
        body = BodyText(_call("execute", sql, "timeout=timeout"))
        return_ = FnReturnText().add("str")
        return FnText(sql.source.name.lower(), params, body, return_).gen()

    def _execmany(self, sql: AnalyzedSQL):
        """Execute an SQL *command* for each sequence of arguments in *args*.

        Example:

        .. code-block:: pycon

            >>> await con.executemany('''
            ...     INSERT INTO mytab (a) VALUES ($1, $2, $3);
            ... ''', [(1, 2, 3), (4, 5, 6)])

        :param command: Command to execute.
        :param args: An iterable containing sequences of arguments.
        :param float timeout: Optional timeout value in seconds.
        :return None: This method discards the results of the operations.
        """
        params = self._build_fn_params(sql, many=True, record_class=False)
        body = BodyText(
            f"return await conn.executemany({sql.source.name.upper()}, args, timeout=timeout)"
        )
        return_ = FnReturnText().add("None")
        return FnText(sql.source.name.lower(), params, body, return_).gen()


def _row(types: Iterable[str]) -> str:
    types = list(types)
    return f"tuple[{', '.join(types)}]" if types else "tuple[()]"


def _call(method: str, sql: AnalyzedSQL, *extra: str) -> str:
    args = [sql.source.name.upper(), *sql.typed_params.keys(), *extra]
    return f"return await conn.{method}({', '.join(args)})"
