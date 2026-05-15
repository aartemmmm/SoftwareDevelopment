-- Dirty Read: подготовка данных
TRUNCATE TABLE bank_accounts RESTART IDENTITY;
INSERT INTO bank_accounts (owner, balance) VALUES
    ('Алиса', 5000.00),
    ('Борис', 3000.00);

SELECT * FROM bank_accounts ORDER BY id;
