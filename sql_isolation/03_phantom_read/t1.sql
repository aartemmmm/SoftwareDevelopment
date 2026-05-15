-- T1: один и тот же range-query дважды
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T1 first count' AS step, COUNT(*) AS expensive_cnt
FROM products
WHERE price > 30000;

SELECT pg_sleep(10);

SELECT 'T1 second count' AS step, COUNT(*) AS expensive_cnt
FROM products
WHERE price > 30000;

COMMIT;
