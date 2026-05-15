-- T2 FIX: ждёт блокировку FOR UPDATE
SELECT pg_sleep(3);

BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T2 waits on lock' AS step, quantity
FROM warehouse
WHERE id = 1
FOR UPDATE;

UPDATE warehouse
SET quantity = quantity - 5
WHERE id = 1;

COMMIT;

SELECT 'T2 final check' AS step, quantity
FROM warehouse
WHERE id = 1;
