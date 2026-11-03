import keyword
import re


def normalize_name(ns: str) -> str:
    """valid Python name: "my-app" -> my_app, "2fa" -> _2fa, "class" -> class_"""
    name = re.sub(r"\W", "_", ns)
    name = name if name.isidentifier() else f"_{name}"
    return f"{name}_" if keyword.iskeyword(name) else name


def unique_names(names: list[str]) -> list[str]:
    """duplicates get a number: id, id -> id, id_2"""
    out: list[str] = []
    for name in names:
        unique, k = name, 2
        while unique in out:
            unique, k = f"{name}_{k}", k + 1
        out.append(unique)
    return out


def fields(fs: list[tuple[str, str]]) -> tuple[list[str], bool]:
    """output fields, duplicates numbered (id, id -> id, id_2); False: TypedDict"""
    names = unique_names([name for name, _ in fs])
    return names, all(isidentifier(n) and n[:2] != "__" for n in names)


def camel_case(s: str):
    """class name: "user_account" -> UserAccount"""
    return "".join(w.capitalize() for w in s.split("_"))


def isidentifier(ident: str) -> bool:
    """usable as a Python name: an identifier and not a keyword"""
    return ident.isidentifier() and not keyword.iskeyword(ident)
