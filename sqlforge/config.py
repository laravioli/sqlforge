from pathlib import Path
from typing import Annotated, Any, Literal

from msgspec import DecodeError, Meta, Struct, convert, toml
from msgspec.structs import replace


class ConfigError(Exception): ...


_CONFIG_LOOKUP = ["sqlforge.toml", "pyproject.toml"]


class Config(
    Struct, frozen=True, omit_defaults=True, forbid_unknown_fields=True, rename="kebab"
):
    sources: Annotated[list[Path], Meta(min_length=1)]
    out: Path
    dsn: str | None = None
    driver: Literal["asyncpg"] = "asyncpg"
    search_path: tuple[str, ...] = ("public",)
    classes: dict[str, str] = {}

    def resolve(self, cfg_file: Path):
        return replace(
            self,
            sources=[_resolve_source(cfg_file, p) for p in self.sources],
            out=_resolve_path(cfg_file.parent, self.out),
        )


def _dec_hook(type: type[Path], obj: Any) -> Any:
    if type is Path:
        return Path(obj)
    raise NotImplementedError(f"unsupported type: {type}")


def _resolve_source(cfg_file: Path, p: Path) -> Path:
    src = _resolve_path(cfg_file.parent, p)
    _validate_src(cfg_file, src)

    return src


def _resolve_path(base: Path, p: Path) -> Path:
    return (base / p.expanduser()).resolve()


def _validate_src(cfg_file: Path, src: Path):
    if not src.exists():
        raise ConfigError(f"{cfg_file}: source {src} does not exist")

    if src.is_file() and src.suffix != ".sql":
        raise ConfigError(f"{cfg_file}: {src} is not a .sql file")


def load_cfg(start: Path) -> Config:
    start = start.resolve()

    if start.is_file():
        cfg = _read_cfg_file(start)
        if cfg is None:
            raise ConfigError(f"{start}: no [tool.sqlforge] table")
        return cfg.resolve(start)

    home = Path.home().resolve()
    for path in (start, *start.parents):
        for name in _CONFIG_LOOKUP:
            file = path / name
            if file.is_file() and (cfg := _read_cfg_file(file)) is not None:
                return cfg.resolve(file)
        if path == home:
            break

    raise ConfigError(
        f"no sqlforge.toml or pyproject.toml with [tool.sqlforge] found "
        f"in {start} or its parents (up to {home}); run 'sqlforge init' or pass --file"
    )


def _read_cfg_file(cfg_file: Path) -> Config | None:
    try:
        match cfg_file.name:
            case "pyproject.toml":
                doc = toml.decode(cfg_file.read_bytes(), type=dict, dec_hook=_dec_hook)
                tool = doc.get("tool")
                cfg = tool.get("sqlforge") if isinstance(tool, dict) else None
                if cfg is not None:
                    return convert(cfg, type=Config, dec_hook=_dec_hook)
            case _:
                return toml.decode(
                    cfg_file.read_bytes(), type=Config, dec_hook=_dec_hook
                )
    except DecodeError as e:
        raise ConfigError(f"{cfg_file}: {e}") from e
