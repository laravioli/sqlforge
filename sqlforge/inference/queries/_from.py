# ---------------------------------------------------------
# Simple FROM
# ---------------------------------------------------------

SIMPLE_FROM = """
SELECT *
FROM users;
"""


# ---------------------------------------------------------
# FROM with alias
# ---------------------------------------------------------

FROM_ALIAS = """
SELECT *
FROM users AS u;
"""


# ---------------------------------------------------------
# Multiple relations
# PostgreSQL implicit CROSS JOIN
# ---------------------------------------------------------

MULTIPLE_FROM = """
SELECT *
FROM users, orders;
"""


# ---------------------------------------------------------
# Explicit CROSS JOIN
# ---------------------------------------------------------

CROSS_JOIN = """
SELECT *
FROM users
CROSS JOIN orders;
"""


# ---------------------------------------------------------
# INNER JOIN
# ---------------------------------------------------------

INNER_JOIN = """
SELECT *
FROM users
INNER JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# JOIN shorthand
# Equivalent to INNER JOIN
# ---------------------------------------------------------

JOIN = """
SELECT *
FROM users
JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# LEFT JOIN
# ---------------------------------------------------------

LEFT_JOIN = """
SELECT *
FROM users
LEFT JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# LEFT OUTER JOIN
# ---------------------------------------------------------

LEFT_OUTER_JOIN = """
SELECT *
FROM users
LEFT OUTER JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# RIGHT JOIN
# ---------------------------------------------------------

RIGHT_JOIN = """
SELECT *
FROM users
RIGHT JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# RIGHT OUTER JOIN
# ---------------------------------------------------------

RIGHT_OUTER_JOIN = """
SELECT *
FROM users
RIGHT OUTER JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# FULL JOIN
# ---------------------------------------------------------

FULL_JOIN = """
SELECT *
FROM users
FULL JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# FULL OUTER JOIN
# ---------------------------------------------------------

FULL_OUTER_JOIN = """
SELECT *
FROM users
FULL OUTER JOIN orders
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# CROSS JOIN + another relation
# ---------------------------------------------------------

CROSS_JOIN_THREE_TABLES = """
SELECT *
FROM users
CROSS JOIN orders
CROSS JOIN products;
"""


# ---------------------------------------------------------
# Multiple explicit joins
# ---------------------------------------------------------

MULTIPLE_JOINS = """
SELECT *
FROM users
JOIN orders
    ON orders.user_id = users.id
LEFT JOIN payments
    ON payments.order_id = orders.id;
"""


# ---------------------------------------------------------
# Mixed implicit + explicit joins
# ---------------------------------------------------------

MIXED_FROM = """
SELECT *
FROM users, products
LEFT JOIN orders
    ON orders.product_id = products.id;
"""


# ---------------------------------------------------------
# JOIN with aliases
# ---------------------------------------------------------

JOIN_WITH_ALIASES = """
SELECT *
FROM users AS u
LEFT JOIN orders AS o
    ON o.user_id = u.id;
"""


# ---------------------------------------------------------
# Nested join
# ---------------------------------------------------------

NESTED_JOIN = """
SELECT *
FROM users
LEFT JOIN (
    orders
    INNER JOIN payments
        ON payments.order_id = orders.id
)
    ON orders.user_id = users.id;
"""


# ---------------------------------------------------------
# Subquery in FROM
# ---------------------------------------------------------

FROM_SUBQUERY = """
SELECT *
FROM (
    SELECT *
    FROM users
) AS u;
"""


# ---------------------------------------------------------
# Subquery + JOIN
# ---------------------------------------------------------

SUBQUERY_JOIN = """
SELECT *
FROM (
    SELECT *
    FROM users
) AS u
JOIN orders AS o
    ON o.user_id = u.id;
"""


# ---------------------------------------------------------
# Multiple subqueries in FROM
# ---------------------------------------------------------

MULTIPLE_FROM_SUBQUERIES = """
SELECT *
FROM (
    SELECT *
    FROM users
) AS u,
(
    SELECT *
    FROM orders
) AS o;
"""


# ---------------------------------------------------------
# LATERAL subquery
# ---------------------------------------------------------

LATERAL_SUBQUERY = """
SELECT *
FROM users AS u
CROSS JOIN LATERAL (
    SELECT *
    FROM orders AS o
    WHERE o.user_id = u.id
) AS o;
"""


# ---------------------------------------------------------
# VALUES in FROM
# ---------------------------------------------------------

FROM_VALUES = """
SELECT *
FROM (
    VALUES
        (1, 'Alice'),
        (2, 'Bob')
) AS users(id, name);
"""


# ---------------------------------------------------------
# All FROM test queries
# ---------------------------------------------------------

ALL_FROM_QUERIES = {
    "simple_from": SIMPLE_FROM,
    "from_alias": FROM_ALIAS,
    "multiple_from": MULTIPLE_FROM,
    "cross_join": CROSS_JOIN,
    "inner_join": INNER_JOIN,
    "join": JOIN,
    "left_join": LEFT_JOIN,
    "left_outer_join": LEFT_OUTER_JOIN,
    "right_join": RIGHT_JOIN,
    "right_outer_join": RIGHT_OUTER_JOIN,
    "full_join": FULL_JOIN,
    "full_outer_join": FULL_OUTER_JOIN,
    "cross_join_three_tables": CROSS_JOIN_THREE_TABLES,
    "multiple_joins": MULTIPLE_JOINS,
    "mixed_from": MIXED_FROM,
    "join_with_aliases": JOIN_WITH_ALIASES,
    "nested_join": NESTED_JOIN,
    "from_subquery": FROM_SUBQUERY,
    "subquery_join": SUBQUERY_JOIN,
    "multiple_from_subqueries": MULTIPLE_FROM_SUBQUERIES,
    "lateral_subquery": LATERAL_SUBQUERY,
    "from_values": FROM_VALUES,
}
