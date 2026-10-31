from pathlib import Path

from sqlforge.codegen.structures import Output


# TODO header (generated file, do not edit)? cleanup before write?
def write(out: Path, outputs: list[Output]) -> None:
    rendered = {out / o.out: str(o.gen()) for o in outputs}

    out.mkdir(parents=True, exist_ok=True)
    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    for folder, _, _ in out.walk():
        (folder / "__init__.py").touch()
