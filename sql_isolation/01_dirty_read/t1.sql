-- T1: незакоммиченное изменение, затем откат
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

UPDATE bank_accounts
SET balance = balance - 2000
WHERE id = 1;

SELECT 'T1 after update (uncommitted)' AS step, * FROM bank_accounts WHERE id = 1;

SELECT pg_sleep(10);

ROLLBACK;

SELECT 'T1 after rollback' AS step, * FROM bank_accounts WHERE id = 1;
