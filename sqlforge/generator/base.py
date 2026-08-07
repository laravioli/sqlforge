from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Text:
    _string: str

    def add(self, string):
        return replace(self, _string=f"{self._string}{string}")

    def newline(self):
        return replace(self, _string=(f"{self._string}\n"))

    def indent(self):
        return replace(self, _string=f"{self._string}    ")

    def import_(self, module: str):
        return replace(self, _string=f"{self._string}import {module}")

    def import_from(self, module: str, *objs: str):
        return replace(self, _string=f"{self._string}from {module} import {','.join(objs)}")

    def __repr__(self):
        return self._string


@dataclass(frozen=True)
class StructGEN(Text):
    @classmethod
    def class_name(cls, name: str):
        return cls(f"class {name.capitalize()}(Struct):\n")

    def add_attribute(self, attr_name: str, attr_type: str):
        return self.indent().add(f"{attr_name}: {attr_type}").newline()

    def __repr__(self):
        return self._string


@dataclass(frozen=True)
class EnumGEN(Text):
    class_name: str

    @staticmethod
    def enum(class_name: str):
        class_name = class_name.capitalize()
        return EnumGEN(_string=f"class {class_name}(StrEnum):\n", class_name=class_name)

    def add_value(self, enum: str, enum_value: str):
        return self.indent().add(f"{enum.upper()}= '{enum_value}'").newline()

    def __repr__(self):
        return self._string
