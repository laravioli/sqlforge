from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from sqlforge.codegen.base import Text
from sqlforge.codegen.structures import File, Schema
from sqlforge.inference.structures import AnalyzedSQL


def group_by_file(sqls: list[AnalyzedSQL]) -> list[File]:
    groups: dict[Path, list[AnalyzedSQL]] = defaultdict(list)
    for sql in sqls:
        groups[sql.origin.file].append(sql)
    return [File(src=g[0].origin.src, file=file, sqls=g) for file, g in groups.items()]


def write(
    out: Path,
    gen_schema: Callable[[], Schema],
    gen_file: Callable[[File, str], Text],
    sqls: list[AnalyzedSQL],
):
    out.mkdir(parents=True, exist_ok=True)
    schema_folder = out / "schema"
    schema_folder.mkdir(exist_ok=True)
    schema = gen_schema().content
    for f, t in schema.items():
        schema_file = schema_folder / f"{f}.py"
        schema_file.write_text(str(t), encoding="utf-8", newline="\n")

    schema_import = ", ".join(schema.keys())
    for file in group_by_file(sqls):
        filepath = out / file.out.with_suffix(".py")
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(
            str(gen_file(file, schema_import)), encoding="utf-8", newline="\n"
        )

    for folder, _, _ in out.walk():
        (folder / "__init__.py").touch()
