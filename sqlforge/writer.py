from pathlib import Path

from sqlforge.codegen.structures import Output


def write(out: Path, outputs: list[Output]) -> None:
    rendered = {out / o.out: o.content for o in outputs}

    out.mkdir(parents=True, exist_ok=True)
    packages = {out}
    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding="utf-8", newline="\n")
        packages.update(p for p in path.parents if p.is_relative_to(out))

    for folder in packages:
        (folder / "__init__.py").touch()
