
--name: select_user:one
/* yolo*/
SELECT ua.*
FROM user_account AS ua /* yola */
WHERE ua.id = :user_id;

--name : update_notif : exec
UPDATE notification n
SET "read" = true
WHERE n.receiver_id = :receiver_id AND n."read" = false;


-- name: delete_notif:exec
DELETE FROM notification n
WHERE n.receiver_id = :receiver_id;


-- name: accept_friend :exec
WITH new_friendship AS (
    INSERT INTO friendship (sender_id, receiver_id, status)
    VALUES (:sender_id,:receiver_id,'pending')
    RETURNING sender_id, receiver_id, id
)
INSERT INTO notification (sender_id, receiver_id, friendship_id, type)
SELECT sender_id, receiver_id, id, 'friend_request' FROM new_friendship;

--name: list_chall:many
SELECT ch.challenge_id, ch.status, ch.color_choice, ch.color, ch.initial_fen, ch.pub_date, ch.time_control, ub AS sender, ub2 AS receiver
FROM challenge ch LEFT OUTER JOIN user_base ub ON ch.sender_id = ub.id LEFT OUTER JOIN user_base ub2 ON ch.receiver_id = ub2.id
WHERE ch.sender_id = :user_id OR ch.receiver_id = :user_id
ORDER BY ch.pub_date DESC;

--name: create_chall:exec
INSERT INTO challenge (challenge_id, sender_id, receiver_id, color_choice, color, time_control)
VALUES (:chall_id,:sender_id,:receiver_id,:color_choice,:color,:time_control);

--name: create_game:exec
INSERT INTO game (game_id, white_id, black_id, status)
VALUES (:game_id,:white_id,:black_id, 'created');

--name: get_notifications:many
SELECT n.*,uas.username AS sender
FROM notification n 
JOIN user_account uas ON n.sender_id = uas.id
WHERE n.receiver_id = :receiver_id
ORDER BY n.created_at DESC;

--name: unread_count:one
SELECT count(*) AS unread_count
FROM notification n
WHERE n.receiver_id = :receiver_id
AND n.read = false;

--name: list_friendship:many
SELECT ua.id, ua.username, uf.last_update, uf.direction
FROM user_account ua
JOIN (
    SELECT friendship.receiver_id AS friend_id, friendship.last_update AS last_update, 'outgoing' AS direction
    FROM friendship
    WHERE friendship.sender_id = :user_id AND friendship.status = :f_status
        UNION ALL
    SELECT friendship.sender_id AS friend_id, friendship.last_update AS last_update, 'incoming' AS direction
    FROM friendship
    WHERE friendship.receiver_id = :user_id AND friendship.status = :f_status) AS uf
ON ua.id = uf.friend_id
ORDER BY uf.last_update DESC;