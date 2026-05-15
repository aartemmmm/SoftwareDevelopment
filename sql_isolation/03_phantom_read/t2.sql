-- T2: вставляет строку, попадающую в диапазон T1
SELECT pg_sleep(3);

BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

INSERT INTO products (name, price)
VALUES ('Видеокарта', 60000.00);

COMMIT;

SELECT 'T2 after insert' AS step, COUNT(*) AS expensive_cnt
FROM products
WHERE price > 30000;
