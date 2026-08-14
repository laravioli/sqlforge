from sqlforge.generator import DomainText, EnumText, StructText, Text

from .datastruct import *


class PgSchemaGenerator:
    def __init__(
        self,
        pg_reg: PGTypeRegister,
        python_reg: PythonTypeRegister,
    ):
        self.pg_reg = pg_reg
        self.python_reg = python_reg

    def generate_schema(self) -> Text:
        txt = (
            Text()
            .import_("asyncpg")
            .import_("datetime")
            .import_("decimal")
            .import_("ipaddress")
            .import_("uuid")
            .newline()
        )

        for pg_text in self._pg_writer():
            txt.add(pg_text).newline()

        return txt

    def _pg_writer(self):
        for pg_type in self.pg_reg.values():
            match pg_type:
                case CompositeType():
                    yield self._composite(pg_type)
                case DomainType():
                    yield self._domain(pg_type)
                case EnumType():
                    yield self._enum(pg_type)

    def _composite(self, composite: CompositeType):
        txt = StructText(composite.name)
        for attr in composite.attributes:
            attr_type = (
                self.python_reg[attr.attr_type]
                if attr.not_null
                else self.python_reg[attr.attr_type] + " | None"
            )
            attr_default = "" if attr.not_null else "None"
            txt.add_attribute(attr.name, attr_type, attr_default)
        return txt

    def _enum(self, enum: EnumType):
        txt = EnumText(enum.name)
        for value in enum.values:
            txt.add_value(value.upper(), value)
        return txt

    def _domain(self, domain: DomainType):
        return DomainText(domain.name, self.python_reg[domain.basetype])
