-- T2: конкурентное списание
SELECT pg_sleep(3);

BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T2 reads' AS step, quantity
FROM warehouse
WHERE id = 1;

UPDATE warehouse
SET quantity = quantity - 5
WHERE id = 1;

COMMIT;

SELECT 'T2 final check' AS step, quantity
FROM warehouse
WHERE id = 1;
