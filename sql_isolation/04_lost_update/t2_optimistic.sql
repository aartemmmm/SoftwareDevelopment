-- T2 FIX: optimistic locking
SELECT pg_sleep(3);

BEGIN;

SELECT 'T2 reads' AS step, quantity, version
FROM warehouse
WHERE id = 1;

UPDATE warehouse
SET quantity = quantity - 5,
    version = version + 1
WHERE id = 1
  AND version = 1;

COMMIT;

SELECT 'T2 rows updated (1=ok)' AS note;
