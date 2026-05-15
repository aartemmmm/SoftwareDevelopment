-- T1 FIX: пессимистичная блокировка
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T1 lock' AS step, quantity
FROM warehouse
WHERE id = 1
FOR UPDATE;

SELECT pg_sleep(10);

UPDATE warehouse
SET quantity = quantity - 3
WHERE id = 1;

COMMIT;

SELECT 'T1 final check' AS step, quantity
FROM warehouse
WHERE id = 1;
