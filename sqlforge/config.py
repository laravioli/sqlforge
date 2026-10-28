from pathlib import Path
from typing import Annotated, Any, Literal

import msgspec
from msgspec import Meta, Struct, toml
from msgspec.structs import fields


class ConfigError(Exception): ...


class Config(
    Struct, frozen=True, omit_defaults=True, forbid_unknown_fields=True, rename="kebab"
):
    inputs: Annotated[list[Path], Meta(min_length=1)]
    output: Path
    dsn: str
    env_file: Path | None = None
    driver: Literal["asyncpg"] = "asyncpg"
    search_path: tuple[str, ...] = ("public",)
    classes: dict[str, str] = {}


FileConfig = msgspec.defstruct(
    "FileConfig",
    [(f.name, f.type | None, None) for f in fields(Config)],
    frozen=True,
    forbid_unknown_fields=True,
    rename="kebab",
)


def find_config(start: Path) -> tuple[Path, dict[str, Any]] | None:
    start = start.resolve()
    home = Path.home().resolve()
    for path in (start, *start.parents):
        for name in ("sqlforge.toml", "pyproject.toml"):
            if (table := _read_table(path / name)) is not None:
                return path, table
        if path == home:
            break
    return None


def _read_table(file: Path) -> dict[str, Any] | None:
    if not file.is_file():
        return None

    try:
        doc = toml.decode(file.read_bytes(), dec_hook=_dec_hook)
    except msgspec.DecodeError as e:
        raise ConfigError(f"{file}: {e}") from e

    if file.name == "pyproject.toml":
        tool = doc.get("tool")
        doc = tool.get("sqlforge") if isinstance(tool, dict) else None
        if doc is None:
            return None  # a pyproject.toml without [tool.sqlforge]: keep searching

    try:
        msgspec.convert(doc, FileConfig, dec_hook=_dec_hook)  # validate the file alone
    except msgspec.ValidationError as e:
        raise ConfigError(f"{file}: {e}") from e

    return doc


def _dec_hook(type: type[Path], obj: Any) -> Any:
    if type is Path:
        return Path(obj)
    else:
        return obj
