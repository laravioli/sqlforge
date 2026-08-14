from __future__ import annotations

from .utils import camel_case

# Base


class Text:
    def __init__(self, string: str = ""):
        self._string = string

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


# Schema


class StructText(Text):
    def __init__(self, name: str):
        self._string = f"class {camel_case(name)}(Struct):\n"

    def add_attribute(self, attr_name: str, attr_type: str, default: str | None = None):
        return (
            self.indent()
            .add(f"{attr_name}: {attr_type}")
            .add(f" = {default}" if default else "")
            .newline()
        )


class EnumText(Text):
    def __init__(self, cls_name: str):
        self._string = f"class {camel_case(cls_name)}(StrEnum):\n"

    def add_value(self, enum: str, enum_value: str):
        return self.indent().add(f"{enum.upper()} = '{enum_value}'").newline()


class DomainText(Text):
    def __init__(self, name: str, python_type: str):
        self._string = f"type {camel_case(name)} = {python_type}\n"


# Functions


class FnParamText(Text):
    def __init__(self, name: str, param_type: str):
        self._string = f"({name}: {param_type}"

    def add_param(self, name: str, param_type: str, default: str | None = None):
        self.add(f", {name.lower()}: {param_type}").add(f" = {default}" if default else "")
        return self

    def asterix(self):
        self.add(", *")
        return self

    def _close(self):
        self._string += ")"
        return self


class BodyText(Text):
    def __init__(self, stmt: str = ""):
        self._string = stmt + "\n" if stmt else ""

    def add_statement(self, stmt: str | Text):
        self.indent().add(stmt if isinstance(stmt, str) else stmt._string).newline()
        return self


class FnReturnText(Text):
    def __init__(self):
        self._string = " -> "


class FnText(Text):
    param: FnParamText
    body: BodyText
    return_: FnReturnText | None

    def __init__(
        self,
        name: str,
        param: FnParamText,
        body: BodyText,
        return_: FnReturnText | None = None,
        async_=True,
    ):
        self._string = f"{'async def ' if async_ else 'def'}{name}"
        self.param = param
        self.body = body
        self.return_ = return_

    def gen(self):
        return (
            self.add(self.param._close())
            .add(self.return_ if self.return_ else "")
            .add(":")
            .newline()
            .indent()
            .add(self.body)
            .newline()
        )
