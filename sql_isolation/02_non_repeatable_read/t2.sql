-- T2: обновляет строку между двумя чтениями T1
SELECT pg_sleep(3);

BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

UPDATE employees
SET salary = 65000.00
WHERE id = 1;

COMMIT;

SELECT 'T2 after commit' AS step, salary
FROM employees
WHERE id = 1;
