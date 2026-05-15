-- T2: попытка прочитать незакоммиченные данные (dirty read)
BEGIN;
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT 'T2 read while T1 uncommitted' AS step, balance
FROM bank_accounts
WHERE id = 1;

COMMIT;
