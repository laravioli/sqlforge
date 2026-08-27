from __future__ import annotations

from functools import singledispatchmethod
from typing import TypeGuard

from sqlglot.schema import MappingSchema

from ..converter import TypeConverter
from ..datastruct import *


class SchemaGenerator:
    def __init__(self, register: PGTypeRegister):
        self._register = register
        self._attr_converter = AttrTypeConverter(register=register)

    def gen(self) -> MappingSchema:
        # NOTE we'll feed sqlglot with all user defined composite-type
        # NOTE not sure if its right tho
        composites = filter(is_composite, self._register.values())
        return MappingSchema(
            schema={t.name: self.gen_one(t) for t in composites}, dialect="postgres"
        )

    def gen_one(self, comp: CompositeType):
        conv = self._attr_converter
        reg = self._register
        return {attr.name: conv._convert(reg[attr.attr_type]) for attr in comp.attributes}


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
