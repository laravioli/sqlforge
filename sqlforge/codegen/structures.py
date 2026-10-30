from dataclasses import dataclass
from pathlib import Path

from sqlforge.inference.structures import AnalyzedSQL


@dataclass(frozen=True, slots=True)
class File:
    src: Path
    file: Path
    sqls: list[AnalyzedSQL]

    @property
    def folder(self):
        return self.file.parent

    @property
    def filename(self):
        return self.file.name

    @property
    def out(self):
        return self.file.relative_to(self.src.parent)

    @property
    def depth(self):
        return len(self.out.parts)
