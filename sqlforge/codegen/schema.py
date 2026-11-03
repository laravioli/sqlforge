import re

from sqlforge.introspection.structures import (
    CompositeType,
    DomainType,
    EnumType,
    PGAttribute,
    PGTypeRegister,
)

from .base import DomainText, EnumText, StructText, Text
from .structures import PYTHON_ANY, DriverCtx
from .utils import camel_case, isidentifier


class SchemaCodegen:
    def __init__(self, ctx: DriverCtx):
        self.ctx = ctx

    def gen(self, ns: str):
        txt = (
            Text()
            .import_from("__future__", "annotations")
            .import_(*self.ctx.default_import)
        )

        schema_import = [n for n in self.ctx.schema_import if n != ns]
        if schema_import:
            txt.import_from(
                ".", ", ".join(self.ctx.normalize(sc) for sc in schema_import)
            )

        txt.newline()

        for pg_text in self._writer(ns):
            txt.add(pg_text).newline()

        return txt

    def _writer(self, ns: str):
        for pg_type in (v for v in self.ctx.pg_types.values() if v.ns == ns):
            if not isidentifier(camel_case(pg_type.name)):  # Any
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

    def _domain(self, domain: DomainType, ns: str):
        pt = self.ctx.python_types[domain.basetype]
        return DomainText(domain.name, pt.hint if pt.ns == ns else pt.qualified_hint)

    def _enum(self, enum: EnumType):
        txt = EnumText(enum.name)
        for name, value in zip(_member_names(enum.values), enum.values):
            txt.add_value(name, value)
        return txt

    def _hint(self, attr: PGAttribute, ns: str) -> str:
        pt = self.ctx.python_types[attr.attr_type]
        hint = pt.hint if pt.ns == ns else pt.qualified_hint
        return f"{hint} | None" if attr.nullable and pt is not PYTHON_ANY else hint


def get_user_schema_names(pg_type_register: PGTypeRegister):
    return sorted({v.ns for v in pg_type_register.values() if v.ns != "pg_catalog"})


def _member_names(labels: list[str]) -> list[str]:
    names: list[str] = []
    for i, label in enumerate(labels):
        base = re.sub(r"\W+", "_", label.upper()).strip("_")
        name = next(
            n for n in (base, f"_{base}", f"_{i}") if n.isidentifier() and n != "_"
        )
        unique, k = name, 2
        while unique in names:  # "a" and "A" -> A, A_2
            unique, k = f"{name}_{k}", k + 1
        names.append(unique)
    return names
