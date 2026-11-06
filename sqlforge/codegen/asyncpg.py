from collections.abc import Iterable
from typing import Literal

from sqlforge.inference.structures import AnalyzedSQL
from sqlforge.introspection.structures import (
    ArrayType,
    BaseType,
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGTypeRegister,
    PseudoType,
    RangeType,
    TypeKind,
)
from sqlforge.structures import QueryKind
from sqlforge.utils import camel_case, isidentifier

from .base import BodyText, FnParamText, FnReturnText, FnText, Text
from .schema import SchemaCodegen
from .structures import (
    PYTHON_ANY,
    Driver,
    File,
    Output,
    PythonArrayType,
    PythonRangeType,
    PythonRegularType,
    PythonType,
    Schema,
    TypedSQL,
)

_MANY = (QueryKind.FETCHMANY, QueryKind.EXECMANY)


class AsyncpgCodegen:
    def __init__(
        self,
        pg_types: PGTypeRegister,
        format: Literal["dataclass", "msgspec", "pydantic"],
    ):
        self.driver = Driver(
            pg_types, {oid: _python_type(oid, pg_types) for oid in pg_types}, format
        )
        self._schema = SchemaCodegen(self.driver, format)

    def gen(self, sqls: list[AnalyzedSQL]) -> list[Output]:
        return [
            *[
                Schema.make(sc, self._schema.gen(sc))
                for sc in self.driver.schema_import
            ],
            *[
                File(
                    fs[0].origin.src,
                    filepath,
                    self._file(
                        [
                            TypedSQL.convert(source, self.driver.python_types)
                            for source in fs
                        ]
                    ),
                )
                for filepath, fs in File.groups(sqls).items()
            ],
        ]

    def _file(self, sqls: list[TypedSQL]):
        body = Text()
        for fn in _fn_writer(sqls):
            body.add(fn).newline()
        used = {"asyncpg", "typing"}.union(*(sql.modules for sql in sqls))
        schemas = used.intersection(self.driver.normalized_schema_import)
        imports = (
            Text("from __future__ import annotations")
            .newline()
            .newline()
            .import_(*sorted(used - schemas))
            .newline()
            .import_from(f"{'.' * sqls[0].origin.depth}schema", *sorted(schemas))
        )
        if any(sql.source.kind in _MANY for sql in sqls):
            imports.import_from(
                "collections.abc",
                "Iterable",
            )

        return imports.newline().add(body)


# Hint

_BASE_TYPE: dict[str, str] = {
    "record": "tuple",
    "bit": "asyncpg.BitString",
    "varbit": "asyncpg.BitString",
    "bool": "bool",
    "box": "asyncpg.Box",
    "bytea": "bytes",
    "char": "bytes",
    "name": "str",
    "varchar": "str",
    "text": "str",
    "xml": "str",
    "bpchar": "str",
    "cidr": "ipaddress.IPv4Network | ipaddress.IPv6Network",
    "inet": "ipaddress.IPv4Interface | ipaddress.IPv6Interface | ipaddress.IPv4Address | ipaddress.IPv6Address",
    "macaddr": "str",
    "macaddr8": "str",
    "circle": "asyncpg.Circle",
    "date": "datetime.date",
    "time": "datetime.time",
    "timetz": "datetime.time",
    "timestamp": "datetime.datetime",
    "timestamptz": "datetime.datetime",
    "interval": "datetime.timedelta",
    "float4": "float",
    "float8": "float",
    "int2": "int",
    "int4": "int",
    "int8": "int",
    "numeric": "decimal.Decimal",
    "json": "str",
    "jsonb": "str",
    "line": "asyncpg.Line",
    "lseg": "asyncpg.LineSegment",
    "money": "str",
    "path": "asyncpg.Path",
    "point": "asyncpg.Point",
    "polygon": "asyncpg.Polygon",
    "uuid": "uuid.UUID",
    "tid": "tuple",
    "oid": "int",
    "xid": "int",
    "xid8": "int",
    "cid": "int",
}

_RANGE = "asyncpg.Range[{}]"
_MULTIRANGE = "list[asyncpg.Range[{}]]"


def _python_type(oid: Oid, pg_types: PGTypeRegister) -> PythonType:

    match pg_types[oid]:
        case ArrayType(elemtype=elem):
            return PythonArrayType(_python_type(elem, pg_types))

        case RangeType(kind=kind, range_subtype=sub):
            return PythonRangeType(
                _python_type(sub, pg_types),
                _MULTIRANGE if kind is TypeKind.MULTI_RANGE else _RANGE,
            )

        case CompositeType() | DomainType() | EnumType() as t if t.is_user_defined:
            name = camel_case(t.name)
            if isidentifier(name):
                return PythonRegularType(name, t.ns)
            if isinstance(t, DomainType):
                return _python_type(
                    t.basetype, pg_types
                )  # no alias generated: base type
            return PYTHON_ANY  # "my-table", "Weird Type"

        case DomainType(basetype=base):
            return _python_type(base, pg_types)

        case BaseType(name=name) | PseudoType(name=name):
            pg_base = _BASE_TYPE.get(name)
            return PythonRegularType(pg_base) if pg_base is not None else PYTHON_ANY

        case _:  # system composite types
            return PYTHON_ANY


# Function


def _fn_writer(sqls: list[TypedSQL]):
    for sql in sqls:
        txt = (
            Text(f"{sql.name.upper()}: typing.Final[str] = {sql.source.text!r}")
            .newline()
            .newline()
        )

        match sql.source.kind:
            case QueryKind.ONE:
                txt.add(_one(sql))
            case QueryKind.MANY:
                txt.add(_many(sql))
            case QueryKind.FETCHVAL:
                txt.add(_fetchval(sql))
            case QueryKind.FETCHMANY:
                txt.add(_fetchmany(sql))
            case QueryKind.EXEC:
                txt.add(_exec(sql))
            case QueryKind.EXECMANY:
                txt.add(_execmany(sql))
        yield txt


def _build_fn_params(sql: TypedSQL, *, many=False, record_class=True):
    params = FnParamText("conn", "asyncpg.Connection")
    if many:
        params.add_param(
            "args",
            f"Iterable[{_row(sql.param_hints.values())}]",
        ).asterix()
    else:
        for name, hint in sql.param_hints.items():
            params.add_param(name, hint)
    params.add_param("timeout", "float | None", "None")
    if record_class:
        # the argument is a class, not a record
        params.add_param("record_class", "type[asyncpg.Record] | None", "None")
    return params


def _one(sql: TypedSQL):
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

    params = _build_fn_params(sql)
    body = BodyText(
        _call("fetchrow", sql, "timeout=timeout", "record_class=record_class")
    )
    return_ = FnReturnText().add(f"{_row(sql.result_hints)} | None")
    return FnText(sql.source.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _many(sql: TypedSQL):
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
    params = _build_fn_params(sql)
    body = BodyText(_call("fetch", sql, "timeout=timeout", "record_class=record_class"))
    return_ = FnReturnText().add(f"list[{_row(sql.result_hints)}]")
    return FnText(sql.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _fetchval(sql: TypedSQL):
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
    params = _build_fn_params(sql, record_class=False).add_param(
        "column", f"typing.Literal[{columns}]", "0"
    )
    body = BodyText(_call("fetchval", sql, "column=column", "timeout=timeout"))
    # None once (no row or NULL value), then the distinct types a column may hold
    values = dict.fromkeys(
        t.qualified_hint
        for (_, t), null in zip(sql.typed_attrs, sql.nulls)
        if null.may_value
    )
    return_ = FnReturnText().add(" | ".join([*values, "None"]))
    return FnText(sql.source.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _fetchmany(sql: TypedSQL):
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
    params = _build_fn_params(sql, many=True)
    body = BodyText(
        f"return await conn.fetchmany({sql.source.name.upper()}, args, timeout=timeout, record_class=record_class)"
    )
    return_ = FnReturnText().add(f"list[{_row(sql.result_hints)}]")
    return FnText(sql.source.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _exec(sql: TypedSQL):
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
    params = _build_fn_params(sql, record_class=False)
    body = BodyText(_call("execute", sql, "timeout=timeout"))
    return_ = FnReturnText().add("str")
    return FnText(sql.source.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _execmany(sql: TypedSQL):
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
    params = _build_fn_params(sql, many=True, record_class=False)
    body = BodyText(
        f"return await conn.executemany({sql.source.name.upper()}, args, timeout=timeout)"
    )
    return_ = FnReturnText().add("None")
    return FnText(sql.source.name.lower(), params, body, return_, doc=_doc(sql)).gen()


def _row(types: Iterable[str]) -> str:
    types = list(types)
    return f"tuple[{', '.join(types)}]" if types else "tuple[()]"


def _call(method: str, sql: TypedSQL, *extra: str) -> str:
    args = [sql.source.name.upper(), *sql.typed_params.keys(), *extra]
    return f"return await conn.{method}({', '.join(args)})"


def _doc(sql: TypedSQL) -> str:
    """the query as a raw docstring, in a ``` block for IDE hovers;
    none if it contains \"\"\" (that would end it)"""
    text = sql.source.text
    if '"""' in text:
        return ""
    body = text.expandtabs().replace("\n", "\n    ")
    return 'r"""\n    ```\n    ' + body + '\n    ```\n    """'
