from pathlib import Path
from typing import NotRequired, TypedDict


class Driver(TypedDict):
    name: str
    dialect: str
    options: NotRequired[dict]


class Config(TypedDict):
    input: Path
    ouput: Path
    dsn: str
    driver: Driver


class ConfigLoader:
    def load(self):
        pass

    def find(self):
        pass
