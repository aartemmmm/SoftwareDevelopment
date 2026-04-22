# forpeep — Dating Telegram Bot

Монолитное dating-приложение на базе Telegram Bot API с трёхуровневой системой рейтинга, Redis-кэшированием ленты анкет и асинхронной обработкой событий через RabbitMQ + Celery.

## Tech Stack

| Слой | Технологии |
|---|---|
| Bot | Python 3.14, aiogram 3.x |
| Database | PostgreSQL 16, SQLAlchemy 2 (async), asyncpg |
| Cache | Redis 7 |
| Task Queue | Celery 5, RabbitMQ 3.13 |
| File Storage | MinIO (S3-compatible) |
| Config | python-dotenv, Pydantic |

## Architecture

Единый монолитный процесс, разбитый на логические модули:

```
app/
├── db/
│   ├── base.py            # engine, async_session
│   └── models.py          # ORM-модели (8 таблиц)
├── modules/
│   ├── rating.py          # 3-уровневый рейтинг
│   ├── matching.py        # лента, лайк/скип, мэтчи
│   ├── cache.py           # Redis feed cache
│   └── storage.py         # MinIO upload
└── bot/
    ├── middlewares.py      # DB session + Redis injection
    ├── keyboards.py        # inline/reply keyboards, CallbackData
    └── handlers/
        ├── registration.py # /start, FSM регистрации
        ├── profile.py      # просмотр и редактирование анкеты
        └── feed.py         # лента, like/skip, мэтчи
```

MQ (RabbitMQ) используется внутри монолита для асинхронной обработки событий (пересчёт рейтинга после лайка) и не является шиной межсервисного взаимодействия.

## Rating System

Реализована трёхуровневая модель рейтинга:

**Level 1 — Primary score** (полнота анкеты)
- Имя, возраст, пол, описание, город → до 7 баллов
- Количество фото (1 фото = +2, 2+ = +5) → до 5 баллов
- Нормализуется до шкалы 0–10

**Level 2 — Behavioral score** (поведение)
- Количество полученных лайков (насыщение при 50) → до 4 баллов
- Соотношение лайков к пропускам → до 3 баллов
- Частота мэтчей относительно лайков → до 3 баллов

**Level 3 — Final score** (комбинированный)
```
final = primary × 0.3 + behavioral × 0.7
```

## Feed Cache Strategy

```
Открытие ленты
      │
      ▼
Redis cache пуст? ──Yes──► Загрузить 10 кандидатов из БД (ORDER BY final_score DESC)
      │                              │
      │                     Первый → вернуть сразу
      │                     2–10   → положить в Redis (TTL 1h)
      No
      │
      ▼
pop_from_feed(user_id) → следующий ID (O(1))
```

На 10-й анкете кэш опустошается, при следующем запросе цикл повторяется.

## Prerequisites

- Docker & Docker Compose
- Python 3.14+
- Telegram Bot Token ([BotFather](https://t.me/BotFather))

## Quick Start

**1. Клонировать репозиторий и создать окружение**

```bash
git clone <repo-url>
cd chatbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Настроить переменные окружения**

```bash
cp .env.example .env
# Вставить BOT_TOKEN в .env
```

**3. Поднять инфраструктуру**

```bash
docker compose up -d
```

Сервисы:
- PostgreSQL → `localhost:5433`
- Redis → `localhost:6379`
- RabbitMQ → `localhost:5672` (Management UI: `localhost:15672`, guest/guest)
- MinIO → `localhost:9000` (Console: `localhost:9001`, minioadmin/minioadmin)

**4. Запустить приложение**

```bash
# Telegram Bot (основной процесс)
python main.py

# Celery Worker — обработка задач из очереди (отдельный терминал)
celery -A celery_app worker -l info

# Celery Beat — периодический пересчёт рейтингов (отдельный терминал)
celery -A celery_app beat -l info
```

## Environment Variables

```dotenv
BOT_TOKEN=            # Telegram Bot Token

POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
POSTGRES_DB=dating_db

REDIS_URL=redis://localhost:6379

RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=photos
MINIO_SECURE=false
```

## Database Schema

```
users ──────┬──── profiles      (имя, возраст, пол, город, bio)
            ├──── photos        (url MinIO, tg_file_id, is_main)
            ├──── preferences   (preferred_gender, min_age, max_age)
            ├──── ratings       (primary, behavioral, final score)
            ├──── interactions  (from_user → to_user, action: like/skip)
            └──── matches ──── messages
```

## Bot Flow

```
/start
  ├─ Новый пользователь → FSM регистрации (9 шагов)
  │     name → age → gender → city → bio →
  │     pref_gender → pref_min_age → pref_max_age → photo
  └─ Существующий → главное меню

Главное меню
  ├─ 👀 Смотреть анкеты  →  лента с кнопками ❤️ / 👎
  │     ❤️ Лайк  →  запись interaction → проверка мэтча
  │                → Celery задача recalculate_user_rating
  │     👎 Пропустить → запись interaction → следующая анкета
  ├─ 👤 Моя анкета  →  просмотр + редактирование каждого поля
  └─ 💬 Мои мэтчи  →  список совпадений со ссылками
```

## Project Structure

```
chatbot/
├── app/                   # Монолитное приложение
│   ├── db/
│   ├── modules/
│   └── bot/
├── celery_app.py          # Celery + RabbitMQ конфигурация
├── tasks.py               # Фоновые задачи
├── main.py                # Точка входа
├── docker-compose.yml     # PostgreSQL, Redis, RabbitMQ, MinIO
├── requirements.txt
└── docs/
    └── forpeep.md         # Архитектурная документация
```
