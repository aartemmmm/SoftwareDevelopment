-- T1: два чтения одной строки в одной транзакции
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT 'T1 first read' AS step, salary
FROM employees
WHERE id = 1;

SELECT pg_sleep(10);

SELECT 'T1 second read' AS step, salary
FROM employees
WHERE id = 1;

COMMIT;
