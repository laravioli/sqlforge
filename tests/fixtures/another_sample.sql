--name: select_user:one
SELECT ua.*
FROM user_account AS ua
WHERE ua.id = :user_id;

--name: select_worst:one
SELECT *
FROM foo.worst
LIMIT 1;


--name: select_worst_table:one
SELECT *
FROM foo."worst-table"
LIMIT 1;