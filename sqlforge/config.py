from pathlib import Path
from typing import Any, Literal

import msgspec
from msgspec import Struct, toml


class ConfigError(Exception): ...


class Base(Struct, frozen=True, omit_defaults=True, rename="kebab"): ...


class Config(Base, frozen=True, forbid_unknown_fields=True):
    inputs: list[Path]
    output: Path
    dsn: str
    env_file: Path | None = None
    driver: Literal["asyncpg"] = "asyncpg"
    search_path: tuple[str, ...] = ("public",)
    classes: dict[str, str] = {}

    def __post_init__(self):
        if len(self.inputs) == 0:
            raise ConfigError("inputs should contain at least one entry")


class Tool(Base, frozen=True):
    sqlforge: Config | None = None


class PyProject(Base, frozen=True):
    tool: Tool = Tool()


def _dec_hook(type: type[Path], obj: Any) -> Any:
    if type is Path:
        return Path(obj)
    else:
        return obj


def _read[T](file: Path, type_: type[T]) -> T | None:
    if not file.is_file():
        return None
    try:
        return toml.decode(file.read_bytes(), type=type_, dec_hook=_dec_hook)
    except (msgspec.ValidationError, msgspec.DecodeError) as e:
        raise ConfigError(f"{file}: {e}") from e


def get_cfg(start: Path | None = None) -> tuple[Path, Config]:
    start = (start or Path.cwd()).resolve()
    home = Path.home().resolve()

    for path in (start, *start.parents):
        file = path / "sqlforge.toml"
        if (cfg := _read(file, Config)) is not None:
            return file, cfg

        file = path / "pyproject.toml"
        pyproject = _read(file, PyProject)
        if pyproject is not None and pyproject.tool.sqlforge is not None:
            return file, pyproject.tool.sqlforge

        if path == home:
            break

    raise ConfigError(f"could not find a configuration, starting from: {start}")
