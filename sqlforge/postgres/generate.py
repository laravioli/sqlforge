from sqlforge.generator import EnumGEN, StructGEN, Text

from .datastruct import CompositeType, EnumType
from .introspect import TypeRegister
from .typmap import PG_BASE_TYPE


# NOTE i will generate multiple files (so i need multiple text)
def generate(register: TypeRegister):
    text = Text("")

    def get_pg_type(oid: int):
        t = register[oid]
        if t.kind == b"b":
            return PG_BASE_TYPE[t.name]
        return t.name.capitalize()

    def generate_class(c: CompositeType):
        class_text = StructGEN.class_name(c.name)
        for attr in c.attributes:
            class_text = class_text.add_attribute(attr.name, get_pg_type(attr.attr_type))
        return class_text.newline()

    def generate_enum(e: EnumType):
        enum_text = EnumGEN.enum(e.name)
        for v in e.values:
            enum_text = enum_text.add_value(v.upper(), v)
        return enum_text.newline()

    for pg_type in register.values():
        match pg_type:
            case CompositeType():
                text = text.add(str(generate_class(pg_type)))
            case EnumType():
                text = text.add(str(generate_enum(pg_type)))
            case _:
                pass
    return text
