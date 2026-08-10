from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from sqlforge.datastruct import QueryKind

from .utils import camel_case


@dataclass
class Text:
    _string: str

    def add(self, string: str | Text):
        self._string += string if isinstance(string, str) else string._string
        return self

    def newline(self):
        self._string += "\n"
        return self

    def indent(self):
        self._string += "    "
        return self

    def import_(self, module: str):
        self._string += f"import {module}\n"
        return self

    def import_from(self, module: str, *objs: str):
        self._string += f"from {module} import {', '.join(objs)}"
        return self

    def __repr__(self):
        return self._string


@dataclass
class StructText(Text):
    @classmethod
    def struct(cls, name: str):
        return cls(f"class {camel_case(name)}(Struct):\n")

    def add_attribute(self, attr_name: str, attr_type: str):
        return self.indent().add(f"{attr_name}: {attr_type}").newline()


@dataclass
class EnumText(Text):
    class_name: str

    @classmethod
    def enum(cls, class_name: str):
        class_name = camel_case(class_name)
        return cls(
            f"class {class_name}(StrEnum):\n",
            class_name=class_name,
        )

    def add_value(self, enum: str, enum_value: str):
        return self.indent().add(f"{enum.upper()} = '{enum_value}'").newline()


@dataclass
class DomainText(Text):
    @classmethod
    def domain(cls, name: str, python_type: str):
        return cls(f"type {camel_case(name)} = {python_type}\n")


@dataclass
class FunctionParamText(Text):
    @classmethod
    def fn_param(cls, name: str, param_type: str):
        return cls(f"({name}: {param_type}")

    def add_param(self, name: str, param_type: str):
        self.add(f", {name.lower()}: {param_type}")
        return self

    def asterix(self):
        self.add(", *,")
        return self

    def add_param_default(self, name: str, param_type: str, default: str):
        self.add(f", {name.lower()}: {param_type} = {default}")
        return self

    def close(self):
        self._string += ")"
        return self


@dataclass
class FunctionReturnText(Text, ABC):
    kind: QueryKind
    attrs: Sequence[str]

    @classmethod
    def fn_return(cls, kind: QueryKind, attribute_types: Sequence[str] = ()):
        return cls(" -> ", kind=kind, attrs=attribute_types)

    @abstractmethod
    def one(self, *args, **kwargs) -> Self: ...

    @abstractmethod
    def many(self, *args, **kwargs) -> Self: ...

    @abstractmethod
    def fetch(self, *args, **kwargs) -> Self: ...

    @abstractmethod
    def fetchval(self, *args, **kwargs) -> Self: ...

    @abstractmethod
    def exec(self, *args, **kwargs) -> Self: ...

    @abstractmethod
    def execmany(self, *args, **kwargs) -> Self: ...


@dataclass
class FunctionText(Text):
    param: FunctionParamText
    body: Text
    return_: FunctionReturnText

    @classmethod
    def function(
        cls,
        name: str,
        param: FunctionParamText,
        body: Text,
        return_: FunctionReturnText,
        async_=True,  # gigachad
    ):
        if async_:
            kw = "async def "
        else:
            kw = "def "
        return cls(f"{kw}{name}", param, body, return_)

    def generate(self):
        return self.add(self.param).add(self.return_).newline().add(self.body).newline()
