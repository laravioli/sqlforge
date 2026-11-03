import keyword
import re
from pathlib import Path

HINT_ANY = "typing.Any"

_INVALID = re.compile(r"\W")


def py_name(name: str, taken: set[str]) -> str:
    """A valid Python name for a database name, unique within `taken`."""
    ident = name if name.isidentifier() else _INVALID.sub("_", name)
    if not ident.isidentifier():  # empty, or starts with a digit
        ident = f"_{ident}"
    if keyword.iskeyword(ident):
        ident += "_"
    while ident in taken:
        ident += "_"
    taken.add(ident)
    return ident


def camel_case(s: str):
    return "".join(w.capitalize() for w in s.split("_"))


def isidentifier(ident: str) -> bool:
    return ident.isidentifier() and not keyword.iskeyword(ident)


def relative_import_depth(src: Path, file: Path) -> int:
    out = file.with_suffix(".py").relative_to(src.parent)
    return len(out.parts)
