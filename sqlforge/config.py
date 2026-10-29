from pathlib import Path
from typing import Annotated, Any, Literal

import msgspec
from msgspec import Meta, Struct, toml
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

    def resolve_path(self, base: Path):
        return replace(
            self,
            sources=[_resolve_from(base, p) for p in self.sources],
            out=_resolve_from(base, self.out),
        )


def _dec_hook(type: type[Path], obj: Any) -> Any:
    if type is Path:
        return Path(obj)
    else:
        return obj


def _resolve_from(base: Path, p: Path) -> Path:
    return (base / p.expanduser()).resolve()


def load_cfg(start: Path) -> Config:
    start = start.resolve()
    home = Path.home().resolve()

    if start.is_file():
        cfg = _read_cfg_file(start)
        if cfg is not None:
            return cfg.resolve_path(start.parent)
    else:
        path = None
        cfg = None
        home = Path.home().resolve()
        for path in (start, *start.parents):
            for name in _CONFIG_LOOKUP:
                cfg = _read_cfg_file(path / name)
                if cfg is not None:
                    return cfg.resolve_path(path)

            if path == home:
                break

    raise ConfigError(
        f"no sqlforge.toml or pyproject.toml with [tool.sqlforge] found "
        f"in {start} or its parents (up to {home}); "
        f"run 'sqlforge init' or pass --file"
    )


def _read_cfg_file(filepath: Path):
    if filepath.exists():
        try:
            match filepath.name:
                case "pyproject.toml":
                    doc = toml.decode(
                        filepath.read_bytes(), type=dict, dec_hook=_dec_hook
                    )
                    tool = doc.get("tool")
                    cfg = tool.get("sqlforge") if isinstance(tool, dict) else None
                    if cfg is not None:
                        return msgspec.convert(cfg, type=Config)
                case "sqlforge.toml":
                    return toml.decode(
                        filepath.read_bytes(), type=Config, dec_hook=_dec_hook
                    )
        except msgspec.ValidationError as e:
            raise ConfigError(f"{filepath}: {e}") from e
