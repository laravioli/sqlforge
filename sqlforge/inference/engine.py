from __future__ import annotations

import logging
import time

from sqlglot.errors import SqlglotError

from sqlforge.inference.structures import PreparedSQL
from sqlforge.introspection.structures import PGTypeRegister

from .catalog import Catalog
from .context import Context
from .exception import ByPassed, Unsupported
from .infer import Analyzer
from .lattice import MAYBE_NULL
from .prepare import prepare_sql
from .structures import Analysis, AnalyzedSQL, ColumnResult

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, type_register: PGTypeRegister):
        self.catalog = Catalog(type_register)

    def analyze(self, statements: list[PreparedSQL]) -> list[AnalyzedSQL]:

        s = time.perf_counter_ns()
        analyze = [AnalyzedSQL(stmt, self.analyze_one(stmt)) for stmt in statements]
        e = time.perf_counter_ns()
        size = len([a for a in analyze if a.analysis.bypassed is False])
        logger.debug(size)
        if size:
            logger.debug("time : %f ms", (e - s) / (size * 1000000))
        return analyze

    def analyze_one(self, statement: PreparedSQL) -> Analysis:
        if statement.is_empty:
            return Analysis(columns=(), bypassed=False)

        error, internal = None, False
        size = len(statement.result_oids)
        try:
            scope = prepare_sql(statement.source, self.catalog.mapping_schema)
            bypassed = False

            columns = Analyzer(Context(), self.catalog).run(scope).result()
            if size != len(columns):
                raise Unsupported(f"{len(columns)} columns inferred, {size} expected")

        except (SqlglotError, Unsupported) as e:
            columns, bypassed, error = (
                (ColumnResult(MAYBE_NULL),) * size,
                isinstance(e, ByPassed),
                str(e),
            )

        except Exception as e:  # bug
            logger.warning(
                "inference failed on %s, all columns may be NULL",
                statement.name,
                exc_info=e,
            )
            columns, bypassed, error, internal = (
                (ColumnResult(MAYBE_NULL),) * size,
                False,
                repr(e),
                True,
            )

        return Analysis(
            columns=columns,
            bypassed=bypassed,
            error=error,
            internal=internal,
        )
