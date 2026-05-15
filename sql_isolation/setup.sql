-- Общая подготовка: таблицы и тестовые данные для всех аномалий

-- 1) Dirty Read
DROP TABLE IF EXISTS bank_accounts CASCADE;
CREATE TABLE bank_accounts (
    id      SERIAL PRIMARY KEY,
    owner   VARCHAR(50) NOT NULL,
    balance NUMERIC(12, 2) NOT NULL
);
INSERT INTO bank_accounts (owner, balance) VALUES
    ('Алиса', 5000.00),
    ('Борис', 3000.00);

-- 2) Non-repeatable Read
DROP TABLE IF EXISTS employees CASCADE;
CREATE TABLE employees (
    id     SERIAL PRIMARY KEY,
    name   VARCHAR(50) NOT NULL,
    salary NUMERIC(10, 2) NOT NULL
);
INSERT INTO employees (name, salary) VALUES
    ('Иванов',  50000.00),
    ('Петрова', 70000.00),
    ('Сидоров', 45000.00);

-- 3) Phantom Read
DROP TABLE IF EXISTS products CASCADE;
CREATE TABLE products (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(100) NOT NULL,
    price NUMERIC(10, 2) NOT NULL
);
INSERT INTO products (name, price) VALUES
    ('Ноутбук',  85000.00),
    ('Смартфон', 45000.00),
    ('Наушники',  3500.00),
    ('Монитор',  32000.00);

-- 4) Lost Update
DROP TABLE IF EXISTS warehouse CASCADE;
CREATE TABLE warehouse (
    id       SERIAL PRIMARY KEY,
    product  VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL
);
INSERT INTO warehouse (product, quantity) VALUES
    ('Процессор Intel i7', 10),
    ('Видеокарта RTX 4070', 5);

SELECT 'bank_accounts' AS tbl, count(*) FROM bank_accounts
UNION ALL SELECT 'employees',  count(*) FROM employees
UNION ALL SELECT 'products',   count(*) FROM products
UNION ALL SELECT 'warehouse',  count(*) FROM warehouse;
