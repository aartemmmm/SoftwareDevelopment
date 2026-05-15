-- T1: read-modify-write без блокировки (плохой шаблон)
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T1 reads' AS step, quantity
FROM warehouse
WHERE id = 1;

SELECT pg_sleep(10);

UPDATE warehouse
SET quantity = 10 - 3
WHERE id = 1;

COMMIT;

SELECT 'T1 final check' AS step, quantity
FROM warehouse
WHERE id = 1;
