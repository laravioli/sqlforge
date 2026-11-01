from collections import defaultdict
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from sqlforge.inference.structures import AnalyzedSQL
from sqlforge.introspection.structures import (
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGTypeRegister,
)

from .base import DomainText, EnumText, StructText, Text
from .structures import File, PythonType, Schema


def make_schemas(nss: Sequence[str], gen: Callable[[str], Text]) -> list[Schema]:
    return [
        Schema(out=Path("schema") / f"{sc}.py", _gen=partial(gen, sc)) for sc in nss
    ]


def make_files(
    sqls: list[AnalyzedSQL], nss: Sequence[str], gen: Callable[[File, str | None], Text]
) -> list[File]:
    groups: dict[Path, list[AnalyzedSQL]] = defaultdict(list)
    schema_import = ", ".join(nss) if nss else None

    for sql in sqls:
        groups[sql.origin.file].append(sql)

    return [
        File(
            src=g[0].origin.src,
            file=file,
            sqls=g,
            _gen=gen,
            _schema_import=schema_import,
        )
        for file, g in groups.items()
    ]


class SchemaCodegen:
    def __init__(
        self,
        pg_reg: PGTypeRegister,
        python_reg: dict[Oid, PythonType],
    ):
        self.pg_reg = pg_reg
        self.python_reg = python_reg

    def generate_schema(self, ns: str):
        txt = (
            Text()
            .import_from("__future__", "annotations")
            .import_("asyncpg")
            .import_("datetime")
            .import_("decimal")
            .import_("ipaddress")
            .import_("typing")
            .import_("uuid")
            .import_from("enum", "StrEnum")
            .import_from("msgspec", "Struct")
        )

        nss = get_user_schema_names(self.pg_reg)
        nss.remove(ns)
        if nss:
            txt.import_from(".", ", ".join(nss))

        txt.newline()

        for pg_text in self._pg_writer(ns):
            txt.add(pg_text).newline()

        return txt

    def _pg_writer(self, ns: str):
        for pg_type in (v for v in self.pg_reg.values() if v.ns == ns):
            match pg_type:
                case CompositeType():
                    yield self._composite(pg_type, ns)
                case DomainType():
                    yield self._domain(pg_type, ns)
                case EnumType():
                    yield self._enum(pg_type)

    def _composite(self, composite: CompositeType, ns: str):
        txt = StructText(composite.name)
        if not composite.attributes:
            txt.add("   pass")
        else:
            for attr in composite.attributes:
                pt = self.python_reg[attr.attr_type]
                attr_type = pt.hint if pt.ns == ns else pt.qualified_hint
                if attr.nullable:
                    attr_type += " | None"
                    attr_default = "None"
                else:
                    attr_default = ""
                txt.add_attribute(attr.name, attr_type, attr_default)
        return txt

    def _enum(self, enum: EnumType):
        txt = EnumText(enum.name)
        for value in enum.values:
            txt.add_value(value.upper(), value)
        return txt

    def _domain(self, domain: DomainType, ns: str):
        pt = self.python_reg[domain.basetype]
        return DomainText(domain.name, pt.hint if pt.ns == ns else pt.qualified_hint)


def get_user_schema_names(pg_type_register: PGTypeRegister):
    return sorted(
        {v.ns for v in pg_type_register.values() if v.ns != "pg_catalog"}
    )  # TODO : normalize names
