# queries.py

BASIC_COLUMNS = """
SELECT
    id,
    name,
    email
FROM users;
"""


ARITHMETIC = """
SELECT
    id,
    salary,
    salary + 1000 AS increased_salary
FROM employees;
"""


STRING_CONCAT = """
SELECT
    first_name,
    last_name,
    first_name || ' ' || last_name AS full_name
FROM users;
"""


COALESCE = """
SELECT
    id,
    nickname,
    COALESCE(nickname, 'Anonymous') AS display_name
FROM users;
"""


CASE_EXPRESSION = """
SELECT
    id,
    age,
    CASE
        WHEN age >= 18 THEN 'adult'
        WHEN age < 18 THEN 'minor'
        ELSE NULL
    END AS category
FROM users;
"""


SCALAR_SUBQUERY = """
SELECT
    id,
    name,
    (
        SELECT department_name
        FROM departments d
        WHERE d.id = e.department_id
    ) AS department_name
FROM employees e;
"""


IN_SUBQUERY = """
SELECT
    id,
    name
FROM employees
WHERE department_id IN (
    SELECT id
    FROM departments
);
"""


EXISTS_SUBQUERY = """
SELECT
    e.id,
    e.name
FROM employees e
WHERE EXISTS (
    SELECT 1
    FROM departments d
    WHERE d.id = e.department_id
);
"""


CORRELATED_SUBQUERY = """
SELECT
    e.id,
    e.name,
    (
        SELECT COUNT(*)
        FROM orders o
        WHERE o.employee_id = e.id
    ) AS order_count
FROM employees e;
"""


FROM_SUBQUERY = """
SELECT
    x.id,
    x.name
FROM (
    SELECT
        id,
        name
    FROM users
    WHERE active = true
) AS x;
"""


LEFT_JOIN = """
SELECT
    e.id,
    e.name,
    d.department_name
FROM employees e
LEFT JOIN departments d
    ON d.id = e.department_id;
"""


INNER_JOIN = """
SELECT
    e.id,
    e.name,
    d.department_name
FROM employees e
JOIN departments d
    ON d.id = e.department_id;
"""


BASIC_CTE = """
WITH active_users AS (
    SELECT
        id,
        name,
        email
    FROM users
    WHERE active = true
)
SELECT
    id,
    name,
    email
FROM active_users;
"""


CTE_COALESCE = """
WITH users_with_names AS (
    SELECT
        id,
        name,
        COALESCE(name, 'Unknown') AS display_name
    FROM users
)
SELECT
    id,
    display_name
FROM users_with_names;
"""


COMBINED = """
WITH active_employees AS (
    SELECT
        id,
        name,
        department_id,
        salary
    FROM employees
    WHERE active = true
)
SELECT
    e.id,
    COALESCE(e.name, 'Unknown') AS employee_name,
    d.department_name,
    e.salary,
    e.salary * 1.1 AS adjusted_salary,
    (
        SELECT COUNT(*)
        FROM orders o
        WHERE o.employee_id = e.id
    ) AS order_count
FROM active_employees e
LEFT JOIN departments d
    ON d.id = e.department_id;
"""


ALL_QUERIES = [
    BASIC_COLUMNS,
    ARITHMETIC,
    STRING_CONCAT,
    COALESCE,
    CASE_EXPRESSION,
    SCALAR_SUBQUERY,
    IN_SUBQUERY,
    EXISTS_SUBQUERY,
    CORRELATED_SUBQUERY,
    FROM_SUBQUERY,
    LEFT_JOIN,
    INNER_JOIN,
    BASIC_CTE,
    CTE_COALESCE,
    COMBINED,
]
