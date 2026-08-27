from enum import Enum, auto


class Nullability(Enum):
    NULL = auto()
    NON_NULL = auto()
    NULLABLE = auto()
    UNKNOWN = auto()


# 1. Schema NULL / NOT NULL
# 2. JOIN-induced nullability
# 3. NULL literals
# 4. IS NULL / IS NOT NULL
# 5. COALESCE
# 6. CASE
# 7. Basic operators
# 8. Aggregates
# 9. UNION
# 10. Dialect-specific functions
