import typing

USER_TYPE_OIDS: typing.Final = """\
SELECT
    array_agg(t.oid ORDER BY n.nspname, t.typname) AS oids
FROM 
    pg_catalog.pg_type t
JOIN 
    pg_catalog.pg_namespace n ON 
        n.oid = t.typnamespace
WHERE
    n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND t.typtype IN ('c', 'd', 'e', 'r', 'm');
"""


_TYPEINFO: typing.Final = """\
    (
        SELECT
            t.oid                           AS oid,
            ns.nspname                      AS ns,
            t.typname                       AS name,
            t.typtype                       AS kind,
            (CASE WHEN t.typtype = 'd' THEN
                (WITH RECURSIVE typebases(oid, depth) AS (
                    SELECT
                        t2.typbasetype      AS oid,
                        0                   AS depth
                    FROM
                        pg_type t2
                    WHERE
                        t2.oid = t.oid

                    UNION ALL

                    SELECT
                        t2.typbasetype      AS oid,
                        tb.depth + 1        AS depth
                    FROM
                        pg_type t2,
                        typebases tb
                    WHERE
                       tb.oid = t2.oid
                       AND t2.typbasetype != 0
               ) SELECT oid FROM typebases ORDER BY depth DESC LIMIT 1)

               ELSE NULL
            END)                            AS basetype,
            t.typelem                       AS elemtype,
            COALESCE(
                range_t.rngsubtype,
                multirange_t.rngsubtype)    AS range_subtype,
            (CASE WHEN t.typtype = 'c' THEN
                (SELECT
                    array_agg(ia.atttypid ORDER BY ia.attnum)
                FROM
                    pg_attribute ia
                    INNER JOIN pg_class c
                        ON (ia.attrelid = c.oid)
                WHERE
                    ia.attnum > 0 AND NOT ia.attisdropped
                    AND c.reltype = t.oid)

                ELSE NULL
            END)                            AS attrtypoids,
            (CASE
                WHEN t.typtype = 'c' THEN
                    (
                        SELECT jsonb_agg(
                            jsonb_build_object(
                                'attr_type',   ia.atttypid::int,
                                'name',        ia.attname,
                                'position',    ia.attnum,
                                'not_null',    ia.attnotnull
                            )
                            ORDER BY ia.attnum
                        )
                        FROM pg_attribute ia
                        INNER JOIN pg_class c
                            ON ia.attrelid = c.oid
                        WHERE
                            c.reltype = t.oid
                            AND ia.attnum > 0
                            AND NOT ia.attisdropped
                    )
                ELSE NULL
            END)                            AS attributes
        FROM
            pg_catalog.pg_type AS t
            INNER JOIN pg_catalog.pg_namespace ns ON (
                ns.oid = t.typnamespace)
            LEFT JOIN pg_range range_t ON (
                t.oid = range_t.rngtypid
            )
            LEFT JOIN pg_range multirange_t ON (
                t.oid = multirange_t.rngmultitypid
            )
    )
"""

LOOKUP_TYPES = f"""\
WITH RECURSIVE typeinfo_tree(
    oid, ns, name, kind, basetype, elemtype,
    range_subtype, attrtypoids, attributes, depth)
AS (
    SELECT
        ti.oid, ti.ns, ti.name, ti.kind, ti.basetype,
        ti.elemtype, ti.range_subtype,
        ti.attrtypoids, ti.attributes, 0
    FROM
        {_TYPEINFO} AS ti
    WHERE
        ti.oid = any($1::oid[])

    UNION ALL

    SELECT
        ti.oid, ti.ns, ti.name, ti.kind, ti.basetype,
        ti.elemtype, ti.range_subtype,
        ti.attrtypoids, ti.attributes, tt.depth + 1
    FROM
        {_TYPEINFO} ti,
        typeinfo_tree tt
    WHERE
        (tt.elemtype IS NOT NULL AND ti.oid = tt.elemtype)
        OR (tt.attrtypoids IS NOT NULL AND ti.oid = any(tt.attrtypoids))
        OR (tt.range_subtype IS NOT NULL AND ti.oid = tt.range_subtype)
        OR (tt.basetype IS NOT NULL AND ti.oid = tt.basetype)
)

SELECT DISTINCT
    *,
    basetype::regtype::text AS basetype_name,
    elemtype::regtype::text AS elemtype_name,
    range_subtype::regtype::text AS range_subtype_name
FROM
    typeinfo_tree
ORDER BY
    depth DESC
"""


TYPE_ENUM = """\
SELECT
    n.nspname AS schema_name,
    t.typname AS type_name,
  ARRAY_AGG(e.enumlabel ORDER BY e.enumsortorder) AS values
FROM 
    pg_type AS t
JOIN pg_enum AS e ON
    e.enumtypid = t.oid
JOIN pg_namespace AS n ON
    n.oid = t.typnamespace
    AND NOT n.nspname IN ('pg_catalog', 'information_schema')
GROUP BY
  n.nspname,
  t.typname
"""

# NOTE _TYPEINFO and LOOKUP_TYPES are slightly modified version of asyncpg introspection queries
# NOTE require PG > 13
