from collections import defaultdict
from pathlib import Path

from sqlforge.codegen.structures import File
from sqlforge.inference.structures import AnalyzedSQL


def group_by_file(sqls: list[AnalyzedSQL]) -> list[File]:
    groups: dict[Path, list[AnalyzedSQL]] = defaultdict(list)
    for sql in sqls:
        groups[sql.origin.file].append(sql)
    return [File(src=g[0].origin.src, file=file, sqls=g) for file, g in groups.items()]


def write(out: Path):
    pass
