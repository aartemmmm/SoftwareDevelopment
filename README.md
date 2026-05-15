# forpeep — Dating Telegram Bot

Монолитное dating-приложение на базе Telegram Bot API с трёхуровневой системой рейтинга, Redis-кэшированием ленты анкет, событийной архитектурой через RabbitMQ и полным CI/CD пайплайном.

---

## Содержание

1. [Tech Stack](#tech-stack)
2. [Структура проекта](#структура-проекта)
3. [Быстрый старт (локально)](#быстрый-старт-локально)
4. [Полный запуск через Docker](#полный-запуск-через-docker)
5. [Запуск тестов](#запуск-тестов)
6. [CI/CD — GitHub Actions](#cicd--github-actions)
7. [Переменные окружения](#переменные-окружения)
8. [Схема базы данных](#схема-базы-данных)
9. [Система рейтинга](#система-рейтинга)
10. [Стратегия кэширования](#стратегия-кэширования)
11. [Event-driven архитектура](#event-driven-архитектура)
12. [Сервисы и порты](#сервисы-и-порты)

---

## Tech Stack

| Слой | Технологии |
|------|-----------|
| Bot | Python 3.13+, aiogram 3.27 |
| Database | PostgreSQL 16, SQLAlchemy 2 (async), asyncpg |
| Cache | Redis 7 |
| Task Queue | Celery 5, RabbitMQ 3.13 |
| Event Bus | aio-pika (прямое AMQP) |
| File Storage | MinIO (S3-совместимое) |
| CI/CD | GitHub Actions |
| Containers | Docker, Docker Compose |

---

## Структура проекта

```
chatbot/
├── .github/
│   └── workflows/
│       └── ci.yml              # CI: тесты + lint + Docker build
├── app/
│   ├── db/
│   │   ├── base.py             # async engine + sessionmaker
│   │   └── models.py           # 9 ORM-моделей + индексы
│   ├── modules/
│   │   ├── rating.py           # 3-уровневый рейтинг (L1/L2/L3)
│   │   ├── matching.py         # лента, лайк/скип, мэтчи, кэш-прогрев
│   │   ├── cache.py            # Redis feed cache (FIFO батч)
│   │   ├── storage.py          # MinIO upload / presign
│   │   ├── events.py           # Celery event publishers
│   │   ├── event_bus.py        # aio-pika direct AMQP publisher
│   │   └── metrics.py          # Redis счётчики + hourly patterns
│   ├── services/
│   │   ├── notifications.py    # Notification Service (отдельный слой)
│   │   └── event_consumer.py   # Standalone RabbitMQ analytics consumer
│   └── bot/
│       ├── middlewares.py      # DB session + Redis injection
│       ├── keyboards.py        # inline/reply keyboards, CallbackData
│       └── handlers/
│           ├── registration.py # /start, FSM 10 шагов
│           ├── profile.py      # просмотр + редактирование анкеты
│           ├── feed.py         # лента, like/skip, мэтчи
│           └── fallback.py     # catch-all для незарегистрированных
├── tests/
│   ├── conftest.py             # фикстуры + моки БД
│   ├── test_rating.py          # unit-тесты L1/L2/L3
│   ├── test_cache.py           # unit-тесты Redis cache
│   └── test_matching.py        # unit-тесты matchmaking
├── celery_app.py               # Celery + beat расписания
├── tasks.py                    # все фоновые задачи
├── main.py                     # точка входа бота
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
└── .env.example
```

---

## Быстрый старт (локально)

### Шаг 1 — Предварительные требования

```bash
# Проверить версию Python (нужен 3.12+)
python3 --version

# Проверить Docker
docker --version
docker compose version
```

### Шаг 2 — Клонировать репозиторий

```bash
git clone <repo-url>
cd chatbot
```

### Шаг 3 — Создать виртуальное окружение

```bash
python3 -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### Шаг 4 — Установить зависимости

```bash
pip install -r requirements.txt
```

### Шаг 5 — Настроить переменные окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить:

```dotenv
BOT_TOKEN=7123456789:AAF...   # токен от @BotFather
POSTGRES_PASSWORD=your_password
```

Остальные переменные можно оставить по умолчанию для локального запуска.

### Шаг 6 — Поднять инфраструктуру (только сервисы)

```bash
# Поднять только PostgreSQL, Redis, RabbitMQ, MinIO
docker compose up postgres redis rabbitmq minio -d
```

Дождаться успешного старта (проверить healthcheck):

```bash
docker compose ps
# STATUS должен быть "healthy" у всех четырёх сервисов
```

### Шаг 7 — Запустить приложение

Открыть **4 терминала**:

**Терминал 1 — Telegram Bot:**
```bash
source .venv/bin/activate
python main.py
```
Вывод: `Bot started` — бот работает.

**Терминал 2 — Celery Worker:**
```bash
source .venv/bin/activate
celery -A celery_app worker -l info -c 4
```
Вывод: `[tasks.recalculate_all_ratings] ... ready.`

**Терминал 3 — Celery Beat (планировщик):**
```bash
source .venv/bin/activate
celery -A celery_app beat -l info
```
Вывод: `Scheduler: PersistentScheduler`

**Терминал 4 — Event Consumer (аналитика):**
```bash
source .venv/bin/activate
python -m app.services.event_consumer
```
Вывод: `[consumer] Listening on dating_events exchange...`

### Проверить работу

1. Найти бота в Telegram по имени
2. Написать `/start`
3. Пройти регистрацию (10 шагов: имя → возраст → пол → город → bio → интересы → предпочтения → фото)
4. Нажать «👀 Смотреть анкеты»

---

## Полный запуск через Docker

### Запуск одной командой

```bash
# Скопировать и заполнить .env
cp .env.example .env
# Вставить BOT_TOKEN в .env

# Собрать и запустить ВСЕ 8 сервисов
docker compose up --build
```

Поднимаются:
- `postgres` — база данных
- `redis` — кэш
- `rabbitmq` — брокер сообщений
- `minio` — хранилище фото
- `bot` — Telegram бот
- `celery-worker` — обработчик задач
- `celery-beat` — планировщик
- `event-consumer` — аналитический consumer

### Фоновый режим

```bash
docker compose up --build -d

# Следить за логами бота
docker compose logs -f bot

# Следить за Celery
docker compose logs -f celery-worker

# Следить за event-consumer
docker compose logs -f event-consumer
```

### Остановка

```bash
docker compose down

# С удалением данных (осторожно!)
docker compose down -v
```

### Пересборка после изменений кода

```bash
docker compose up --build bot celery-worker celery-beat event-consumer
```

---

## Запуск тестов

### Локально

```bash
# Установить зависимости если ещё не установлены
pip install pytest pytest-asyncio

# Запустить все тесты
python -m pytest tests/ -v

# С отчётом о покрытии (если установлен pytest-cov)
python -m pytest tests/ -v --tb=short
```

Ожидаемый результат: **31 passed**

```
tests/test_cache.py::TestLoadFeedCache::... PASSED
tests/test_matching.py::TestRecordInteraction::... PASSED
tests/test_rating.py::TestLevel1Score::... PASSED
tests/test_rating.py::TestLevel2Score::... PASSED
tests/test_rating.py::TestRecalculateRating::... PASSED
======================== 31 passed in 0.17s ========================
```

### Что тестируется

| Модуль | Тест | Что проверяет |
|--------|------|--------------|
| `test_rating.py` | `TestLevel1Score` (6 тестов) | Полнота профиля → балл L1 |
| `test_rating.py` | `TestLevel2Score` (6 тестов) | Поведение + temporal activity → L2 |
| `test_rating.py` | `TestRecalculateRating` (4 теста) | Финальный балл + freshness multiplier |
| `test_cache.py` | `TestLoadFeedCache` (2 теста) | Загрузка батча в Redis |
| `test_cache.py` | `TestPopFromFeed` (5 тестов) | FIFO-выдача, TTL, пустой кэш |
| `test_cache.py` | `TestLoadPopSequence` (1 тест) | Полный цикл load → drain |
| `test_matching.py` | `TestRecordInteraction` (4 теста) | like/skip, мэтч, дубликаты |

---

## CI/CD — GitHub Actions

CI пайплайн запускается автоматически при каждом `push` и `pull_request`.

### Файл конфигурации

`.github/workflows/ci.yml`

### Jobs

```
push / PR
    │
    ├──► [test] Unit tests (pytest)
    │       Python 3.13
    │       pip install pytest pytest-asyncio sqlalchemy redis python-dotenv
    │       python -m pytest tests/ -v --tb=short
    │
    ├──► [lint] Code style (ruff)
    │       ruff check app/ --select=E,F,W
    │
    └──► [docker] Docker build check  (requires: test)
            docker build -t forpeep-bot:ci .
```

### Настройка в GitHub

1. Загрузить код на GitHub:

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

2. GitHub Actions запустится автоматически. Открыть вкладку **Actions** в репозитории.

3. Статус CI виден в каждом коммите и PR.

### Добавить секреты для деплоя (опционально)

Если нужен автоматический деплой, добавить в `Settings → Secrets and variables → Actions`:

```
BOT_TOKEN          = <Telegram bot token>
POSTGRES_PASSWORD  = <пароль БД>
```

И расширить workflow:

```yaml
- name: Deploy to server
  uses: appleboy/ssh-action@v1
  with:
    host: ${{ secrets.SERVER_HOST }}
    username: ${{ secrets.SERVER_USER }}
    key: ${{ secrets.SSH_KEY }}
    script: |
      cd /app/chatbot
      git pull
      docker compose up --build -d
```

---

## Переменные окружения

Полный список в `.env.example`. Для локального запуска нужно заполнить только `BOT_TOKEN` и `POSTGRES_PASSWORD`.

| Переменная | Дефолт | Описание |
|-----------|--------|---------|
| `BOT_TOKEN` | — | **Обязательно.** Токен от @BotFather |
| `POSTGRES_HOST` | `localhost` | Хост PostgreSQL |
| `POSTGRES_PORT` | `5433` | Порт (5433 при локальном Docker mapping) |
| `POSTGRES_USER` | `postgres` | Пользователь |
| `POSTGRES_PASSWORD` | — | **Обязательно.** Пароль |
| `POSTGRES_DB` | `dating_db` | Имя базы данных |
| `REDIS_URL` | `redis://localhost:6379` | URL Redis |
| `RABBITMQ_HOST` | `localhost` | Хост RabbitMQ |
| `RABBITMQ_PORT` | `5672` | AMQP порт |
| `RABBITMQ_USER` | `guest` | Пользователь |
| `RABBITMQ_PASSWORD` | `guest` | Пароль |
| `MINIO_ENDPOINT` | `localhost:9000` | Endpoint MinIO |
| `MINIO_ACCESS_KEY` | `minioadmin` | Access key |
| `MINIO_SECRET_KEY` | `minioadmin` | Secret key |
| `MINIO_BUCKET` | `photos` | Имя бакета |
| `MINIO_SECURE` | `false` | HTTPS для MinIO |

> **Важно:** В Docker Compose хосты переопределяются автоматически через `environment:` блок (postgres → `postgres`, redis → `redis` и т.д.)

---

## Схема базы данных

```
users
  │
  ├── profiles        (name, age, gender, bio, city, interests)
  ├── photos          (url MinIO, tg_file_id, is_main)
  ├── preferences     (preferred_gender, min_age, max_age)
  ├── ratings         (level1_score, level2_score, final_score, updated_at)
  ├── user_events     (event_type, target_id, created_at)  ← аналитика
  ├── interactions    (from_user_id, to_user_id, action: like/skip, created_at)
  └── matches
        └── chat_messages (sender_id, text, created_at)
```

**Индексы** (созданы для производительности):
- `interactions`: `(from_user_id, to_user_id, action)` — поиск реверс-лайка
- `ratings`: `final_score DESC` — сортировка ленты
- `profiles`: `(gender, age)` — фильтрация по предпочтениям
- `user_events`: `(event_type, created_at)` — аналитические запросы

---

## Система рейтинга

### Level 1 — Полнота анкеты (static quality signal)

Считается один раз при регистрации и при каждом изменении профиля.

| Сигнал | Баллы |
|--------|-------|
| Имя + возраст + пол (базовые) | +6 |
| Описание (bio) заполнено | +2 |
| Город указан | +2 |
| Интересы указаны | +2 |
| 1 фото | +1 |
| 2+ фото | +2 |
| **Максимум** | **14 raw → нормализуется до 0–10** |

### Level 2 — Поведенческий рейтинг (dynamic behavioral signal)

Пересчитывается асинхронно через Celery после каждого лайка.

| Сигнал | Формула | Макс |
|--------|---------|------|
| Объём лайков | `min(received / 50, 1) × 4` | 4 |
| Соотношение лайков к просмотрам | `(likes / views) × 3` | 3 |
| Конверсия лайк → мэтч | `min(matches / likes, 1) × 3` | 3 |
| Временная активность | ≤7 дней = +2, ≤30 дней = +1 | 2 |
| **Максимум (с cap)** | | **10** |

### Level 3 — Итоговый рейтинг (combined + additional factors)

```
base_score = L1 × 0.3 + L2 × 0.7   (если есть поведенческие данные)
base_score = L1                      (новые пользователи без данных)

freshness_multiplier:
  аккаунт ≤ 7 дней  → × 1.15   (+15% boost)
  аккаунт ≤ 30 дней → × 1.05   (+5% boost)
  аккаунт > 30 дней → × 1.00

final_score = min(base_score × freshness_multiplier, 10.0)
```

Новые пользователи временно поднимаются вверх ленты, чтобы получить первые взаимодействия.

---

## Стратегия кэширования

### Feed Cache (Redis list)

```
Пользователь открывает ленту
        │
        ▼
pop_from_feed(user_id)
        │
   cache пуст?
        │
       Yes ──► SELECT 10 кандидатов из БД
        │           ORDER BY final_score DESC
        │           WHERE gender/age = prefs
        │           AND NOT IN (already interacted)
        │      Первый → вернуть пользователю
        │      2–10  → сохранить в Redis (TTL 1h)
        │
       No  ──► Вернуть следующий ID из Redis (O(1))

После каждого like/skip → Celery задача warm_user_feed_cache
(предзагрузка следующего батча, пока пользователь читает текущую анкету)
```

### Hot Profiles (Redis Sorted Set)

```
Ключ: hot_profiles
Каждые 30 минут (Celery Beat):
  SELECT user_id, final_score FROM ratings ORDER BY final_score DESC LIMIT 100
  → ZADD hot_profiles score user_id
  → TTL 30 мин

Использование: быстрый выбор топ-кандидатов без полного скана таблицы
```

### Real-time Metrics (Redis Counters)

```
Ежедневные счётчики:
  metrics:likes:2026-05-15   → INCR при каждом лайке
  metrics:skips:2026-05-15   → INCR при каждом пропуске
  metrics:matches:2026-05-15 → INCR при мэтче

Почасовые паттерны (для анализа активности):
  metrics:hourly:2026-05-15:like  → HASH {hour: count}
  Пример: {'9': 12, '14': 87, '21': 143}

Активные пользователи (HyperLogLog — точный без хранения ID):
  metrics:active_users:2026-05-15 → PFADD user_id
```

---

## Event-driven архитектура

### Двойной MQ-пайплайн

```
Пользователь делает лайк
        │
        ├──► event_bus.publish_like()       [aio-pika, async]
        │         │
        │         └──► RabbitMQ exchange 'dating_events'
        │                   │
        │                   └──► event-consumer (отдельный процесс)
        │                             ├── increment Redis counters
        │                             ├── record hourly pattern
        │                             └── write UserEvent to DB
        │
        └──► events.publish_like_event()    [Celery, async]
                  │
                  └──► RabbitMQ → Celery queue
                            │
                            └──► celery-worker
                                      ├── recalculate_user_rating
                                      ├── record_event_sync → DB
                                      └── warm_user_feed_cache
```

### Celery Beat — расписание задач

| Задача | Расписание | Что делает |
|--------|-----------|-----------|
| `recalculate_all_ratings` | каждый час | Пересчёт рейтинга всех пользователей |
| `warm_active_users_cache` | каждые 15 мин | Прогрев кэша активных за 24ч |
| `refresh_hot_profiles` | каждые 30 мин | Обновление топ-100 в Redis sorted set |
| `cleanup_old_data` | ежедневно 03:00 | Удаление UserEvent старше 90 дней |

### Notification Service

Уведомления вынесены в отдельный слой `app/services/notifications.py`:
- `notify_like()` — показывает карточку лайкнувшего с кнопками лайк/скип
- `notify_match()` — поздравление обоим пользователям со ссылкой на контакт
- `notify_system()` — системные уведомления

---

## Сервисы и порты

| Сервис | Порт (локальный) | URL | Credentials |
|--------|-----------------|-----|-------------|
| PostgreSQL | 5433 | `localhost:5433` | postgres / из .env |
| Redis | 6379 | `redis://localhost:6379` | — |
| RabbitMQ AMQP | 5672 | `amqp://localhost:5672` | guest / guest |
| RabbitMQ UI | 15672 | http://localhost:15672 | guest / guest |
| MinIO API | 9000 | http://localhost:9000 | minioadmin / minioadmin |
| MinIO Console | 9001 | http://localhost:9001 | minioadmin / minioadmin |

### Полезные команды

```bash
# Посмотреть статус всех сервисов
docker compose ps

# Посмотреть очереди RabbitMQ
open http://localhost:15672

# Посмотреть фото в MinIO
open http://localhost:9001

# Подключиться к PostgreSQL
psql -h localhost -p 5433 -U postgres -d dating_db

# Очистить и перезапустить всё
docker compose down -v && docker compose up --build
```
