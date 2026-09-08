# Cross Join

CROSS_JOIN = """
SELECT * FROM t1 CROSS JOIN t2;
"""

CROSS_JOIN_COMMA = """
SELECT * FROM t1, t2;
"""

# Inner Join


INNER_JOIN_NO_QUAL_ON = """
SELECT * FROM t1 JOIN t2 ON t1.num = t2.num;
"""

INNER_JOIN_ON = """
SELECT * FROM t1 INNER JOIN t2 ON t1.num = t2.num;
"""

INNER_JOIN_USING = """
SELECT * FROM t1 INNER JOIN t2 USING (num);
"""

NATURAL_INNER_JOIN = """
SELECT * FROM t1 NATURAL INNER JOIN t2;
"""

# Left Outer Join

LEFT_JOIN_ON = """
SELECT * FROM t1 LEFT JOIN t2 ON t1.num = t2.num;
"""

LEFT_JOIN_USING = """
SELECT * FROM t1 LEFT JOIN t2 USING (num);
"""

# Right Outer Join

RIGHT_JOIN_ON = """
SELECT * FROM t1 RIGHT JOIN t2 ON t1.num = t2.num;
"""

# Full Join

FULL_JOIN_ON = """
SELECT * FROM t1 FULL JOIN t2 ON t1.num = t2.num;
"""

# --- ON condition vs WHERE condition (outer join subtlety) --------------

# Extra condition placed in ON: filtered BEFORE the join happens
LEFT_JOIN_EXTRA_CONDITION_IN_ON = """
SELECT * FROM t1 LEFT JOIN t2 ON t1.num = t2.num AND t2.value = 'xxx';
"""

# Same extra condition placed in WHERE: filtered AFTER the join happens
LEFT_JOIN_EXTRA_CONDITION_IN_WHERE = """
SELECT * FROM t1 LEFT JOIN t2 ON t1.num = t2.num WHERE t2.value = 'xxx';
"""


ALL_QUERIES = {
    "cross_join": CROSS_JOIN,
    "cross_join_comma": CROSS_JOIN_COMMA,
    "inner_join_no_qual": INNER_JOIN_NO_QUAL_ON,
    "inner_join_on": INNER_JOIN_ON,
    "inner_join_using": INNER_JOIN_USING,
    "natural_inner_join": NATURAL_INNER_JOIN,
    "left_join_on": LEFT_JOIN_ON,
    "left_join_using": LEFT_JOIN_USING,
    "right_join_on": RIGHT_JOIN_ON,
    "full_join_on": FULL_JOIN_ON,
    "left_join_extra_condition_in_on": LEFT_JOIN_EXTRA_CONDITION_IN_ON,
    "left_join_extra_condition_in_where": LEFT_JOIN_EXTRA_CONDITION_IN_WHERE,
}
