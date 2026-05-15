-- Phantom Read: подготовка данных
TRUNCATE TABLE products RESTART IDENTITY;
INSERT INTO products (name, price) VALUES
    ('Ноутбук',  85000.00),
    ('Смартфон', 45000.00),
    ('Наушники',  3500.00),
    ('Монитор',  32000.00);

SELECT * FROM products ORDER BY id;
