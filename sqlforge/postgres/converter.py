from abc import ABC, abstractmethod
from functools import singledispatchmethod

from sqlforge.postgres.datastruct import *


class TypeConverter(ABC):
    def __init__(self, register: PGTypeRegister) -> None:
        self.register = register

    def convert(self) -> dict[Oid, str]:
        return {k: self._convert(v) for k, v in self.register.items()}

    @singledispatchmethod
    @abstractmethod
    def _convert(self, t: PGType) -> str:
        raise NotImplementedError()
