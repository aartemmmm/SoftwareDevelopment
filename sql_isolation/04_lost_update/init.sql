-- Lost Update: подготовка данных
TRUNCATE TABLE warehouse RESTART IDENTITY;
INSERT INTO warehouse (product, quantity) VALUES
    ('Процессор Intel i7', 10),
    ('Видеокарта RTX 4070', 5);

SELECT * FROM warehouse ORDER BY id;
