from dataclasses import dataclass
from functools import cached_property, partial
from typing import ClassVar

from sqlforge.core import Config, Info, Pipeline, Recipe
from sqlforge.loader import load

from .generator import generate
from .introspection import introspect_queries
from .transformer import transform


@dataclass
class APGRecipe(Recipe):
    info: ClassVar[Info] = {"dialect": "postgres"}
    config: Config

    @cached_property
    def pipeline(self):
        return (
            Pipeline.start(load)
            .add(transform)
            .add(partial(introspect_queries, dsn=self.config.dsn))
            .add(generate)
        )
