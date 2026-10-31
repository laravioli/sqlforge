from collections import defaultdict
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path

from sqlforge.codegen.base import Text
from sqlforge.codegen.structures import File, Schema
from sqlforge.inference.structures import AnalyzedSQL


def make_schemas(nss: Sequence[str], gen: Callable[[str], Text]) -> list[Schema]:
    return [
        Schema(out=Path("schema") / f"{sc}.py", _gen=partial(gen, sc)) for sc in nss
    ]


def make_files(
    sqls: list[AnalyzedSQL], nss: Sequence[str], gen: Callable[[File, str | None], Text]
) -> list[File]:
    groups: dict[Path, list[AnalyzedSQL]] = defaultdict(list)
    schema_import = ", ".join(nss) if nss else None

    for sql in sqls:
        groups[sql.origin.file].append(sql)

    return [
        File(
            src=g[0].origin.src,
            file=file,
            sqls=g,
            _gen=gen,
            _schema_import=schema_import,
        )
        for file, g in groups.items()
    ]
