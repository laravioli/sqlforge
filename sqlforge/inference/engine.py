from __future__ import annotations

import logging
import time

from sqlglot.errors import SqlglotError

from sqlforge.introspection.structures import PGTypeRegister
from sqlforge.stmt import TypedSQL

from .catalog import Catalog
from .context import Context
from .exception import ByPassed, Unsupported
from .infer import Analyzer
from .lattice import MAYBE_NULL
from .prepare import prepare_sql
from .structures import Analysis, AnalyzedSQL, ColumnResult

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, catalog: Catalog, statements: list[TypedSQL]):
        self.catalog = catalog
        self.statements = statements

    @staticmethod
    def from_register(type_register: PGTypeRegister, statements: list[TypedSQL]):
        return Engine(catalog=Catalog(type_register), statements=statements)

    def analyze(self) -> list[AnalyzedSQL]:

        s = time.perf_counter_ns()
        analyze = [
            AnalyzedSQL(stmt.source, stmt.typed_params, self.analyze_one(stmt))
            for stmt in self.statements
        ]
        e = time.perf_counter_ns()
        size = len([a for a in analyze if a.analysis.bypassed is False])
        logger.debug(size)
        logger.debug("time : %f ms", (e - s) / (size * 1000000))
        return analyze

    def analyze_one(self, statement: TypedSQL) -> Analysis:
        attrs = statement.typed_attrs
        if not attrs:
            return Analysis(columns=(), bypassed=False)

        error, internal = None, False
        try:
            scope = prepare_sql(statement.source, self.catalog.mapping_schema)
            bypassed = False

            nulls = Analyzer(Context(), self.catalog).run(scope).result()
            if len(attrs) != len(nulls):
                raise Unsupported(
                    f"{len(nulls)} columns inferred, {len(attrs)} expected"
                )

        except (SqlglotError, Unsupported) as e:
            nulls, bypassed, error = (
                [MAYBE_NULL] * len(attrs),
                isinstance(e, ByPassed),
                str(e),
            )

        except Exception as e:  # bug
            logger.warning(
                "inference failed on %s, all columns may be NULL",
                statement.name,
                exc_info=e,
            )
            nulls, bypassed, error, internal = (
                [MAYBE_NULL] * len(attrs),
                False,
                repr(e),
                True,
            )

        return Analysis(
            columns=tuple(
                ColumnResult(name, type_, null)
                for (name, type_), null in zip(attrs, nulls)
            ),
            bypassed=bypassed,
            error=error,
            internal=internal,
        )
