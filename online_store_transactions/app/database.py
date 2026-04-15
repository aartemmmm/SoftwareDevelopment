import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5434")
DB_NAME = os.getenv("DB_NAME", "store_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Движок — это соединение с БД
engine = create_engine(DATABASE_URL)

# Фабрика сессий — через сессию делаем все запросы
SessionLocal = sessionmaker(bind=engine)

# Базовый класс для всех ORM-моделей
Base = declarative_base()
