-- Non-repeatable Read: подготовка данных
TRUNCATE TABLE employees RESTART IDENTITY;
INSERT INTO employees (name, salary) VALUES
    ('Иванов',  50000.00),
    ('Петрова', 70000.00),
    ('Сидоров', 45000.00);

SELECT * FROM employees ORDER BY id;
