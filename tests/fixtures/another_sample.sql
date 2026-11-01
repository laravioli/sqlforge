--name: select_user:one
SELECT ua.*
FROM user_account AS ua
WHERE ua.id = :user_id;