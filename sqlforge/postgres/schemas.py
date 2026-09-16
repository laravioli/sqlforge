from __future__ import annotations

from functools import singledispatchmethod
from typing import TypeGuard

from sqlglot.expressions.datatypes import DataType
from sqlglot.schema import MappingSchema

from .converter import TypeConverter
from .structures import *


# TODO: handle namespace prefix
class SchemaGenerator:
    def __init__(self, register: PGTypeRegister):
        self._register = register
        self._attr_converter = AttrTypeConverter(register=register)

    def gen(self) -> MappingSchema:
        mapping = {}
        for rel_type in filter(is_composite, self._register.values()):
            relation = self.gen_one(rel_type)
            mapping[rel_type.name] = relation

        return MappingSchema(schema=mapping, dialect="postgres")

    def gen_one(self, rel_type: CompositeType):
        relation: dict[str, DataType] = {}
        for attr in rel_type.attributes:
            attr_name = attr.name
            dt = DataType.build(self._attr_converter._convert(self._register[attr.attr_type]))
            dt.set("nullable", attr.nullable)
            relation[attr_name] = dt
        return relation


def is_composite(p: PGType) -> TypeGuard[CompositeType]:
    return isinstance(p, CompositeType)


class AttrTypeConverter(TypeConverter):
    @singledispatchmethod
    def _convert(self, t: PGType) -> str:
        if t.elemtype > 0:
            elem = self.register[t.elemtype]
            return f"list[{self._convert(elem)}]"
        return t.name

    @_convert.register
    def _(self, t: RangeType):
        if t.kind is TypeKind.RANGE:
            return "range"
        elif t.kind is TypeKind.MULTI_RANGE:
            return "list[range]"
        else:
            raise ValueError()

    @_convert.register
    def _(self, t: EnumType):
        return "enum"
