ALTER TABLE warehouse
ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

UPDATE warehouse
SET quantity = 10, version = 1
WHERE id = 1;

SELECT * FROM warehouse WHERE id = 1;
