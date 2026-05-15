-- T1 FIX: optimistic locking
BEGIN;

SELECT 'T1 reads' AS step, quantity, version
FROM warehouse
WHERE id = 1;

SELECT pg_sleep(10);

UPDATE warehouse
SET quantity = quantity - 3,
    version = version + 1
WHERE id = 1
  AND version = 1;

COMMIT;
