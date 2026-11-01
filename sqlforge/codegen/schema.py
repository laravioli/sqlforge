import re

from sqlforge.introspection.structures import (
    CompositeType,
    DomainType,
    EnumType,
    Oid,
    PGAttribute,
    PGTypeRegister,
)

from .base import DomainText, EnumText, StructText, Text
from .structures import PYTHON_ANY, PythonType
from .utils import camel_case, isidentifier


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
            .import_(
                "asyncpg",
                "datetime",
                "decimal",
                "enum",
                "ipaddress",
                "typing",
                "uuid",
                "msgspec",
            )
        )

        nss = get_user_schema_names(self.pg_reg)
        nss.remove(ns)
        if nss:
            txt.import_from(".", ", ".join(nss))

        txt.newline()

        for pg_text in self._writer(ns):
            txt.add(pg_text).newline()

        return txt

    def _writer(self, ns: str):
        for pg_type in (v for v in self.pg_reg.values() if v.ns == ns):
            if not isidentifier(camel_case(pg_type.name)):
                continue
            match pg_type:
                case CompositeType():
                    yield self._composite(pg_type, ns)
                case DomainType():
                    yield self._domain(pg_type, ns)
                case EnumType():
                    yield self._enum(pg_type)

    def _composite(self, composite: CompositeType, ns: str):
        attrs = composite.attributes
        if not all(isidentifier(a.name) and not a.name.startswith("__") for a in attrs):
            name = camel_case(composite.name)
            fields = ", ".join(f"{a.name!r}: {self._hint(a, ns)!r}" for a in attrs)
            return Text(f"{name} = typing.TypedDict({name!r}, {{{fields}}})\n")

        txt = StructText(composite.name)
        if not attrs:
            txt.add("   pass")
        for attr in attrs:
            txt.add_attribute(
                attr.name, self._hint(attr, ns), "None" if attr.nullable else ""
            )
        return txt

    def _hint(self, attr: PGAttribute, ns: str) -> str:
        pt = self.python_reg[attr.attr_type]
        hint = pt.hint if pt.ns == ns else pt.qualified_hint
        return f"{hint} | None" if attr.nullable and pt is not PYTHON_ANY else hint

    def _enum(self, enum: EnumType):
        txt = EnumText(enum.name)
        for name, value in zip(_member_names(enum.values), enum.values):
            txt.add_value(name, value)
        return txt

    def _domain(self, domain: DomainType, ns: str):
        pt = self.python_reg[domain.basetype]
        return DomainText(domain.name, pt.hint if pt.ns == ns else pt.qualified_hint)


def get_user_schema_names(pg_type_register: PGTypeRegister):
    return sorted({v.ns for v in pg_type_register.values() if v.ns != "pg_catalog"})


def _member_names(labels: list[str]) -> list[str]:
    names: list[str] = []
    for label in labels:
        name = re.sub(r"\W+", "_", label.upper()).strip("_")
        if not name.isidentifier():  # "", "1ST"
            name = f"_{name}"
        if not name.isidentifier():  # exotic unicode left over
            name = f"_{len(names)}"
        unique, i = name, 2
        while unique in names:
            unique, i = f"{name}_{i}", i + 1
        names.append(unique)
    return names
