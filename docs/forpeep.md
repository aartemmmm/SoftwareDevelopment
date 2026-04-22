#  Описание архитектуры (монолит)

В системе реализовано **единое монолитное приложение**, разделённое на логические модули.  
Все модули работают в рамках одного процесса и одной кодовой базы, но имеют чёткое разделение ответственности.

---

#  Общая архитектура

##  Роль Message Queue (MQ)

В данной архитектуре **MQ используется внутри монолита не для коммуникации между сервисами**, а для:

- разгрузки основного потока обработки запросов  
- выполнения тяжёлых операций асинхронно  
- обработки фоновых задач  
- событийной обработки действий пользователей (likes, matches, messages, rating updates)

 MQ выступает как механизм **асинхронного выполнения задач внутри монолита**, а не как шина межсервисного взаимодействия.

---

#  Users & Profile Module

Отвечает за управление пользователями и их анкетами.

## Функциональность:

- Регистрация через Telegram ID  
- Хранение профиля пользователя:
  - имя  
  - возраст  
  - пол  
  - био  
  - город  
- Управление фотографиями  
- Настройки предпочтений:
  - предпочтительный пол  
  - диапазон возраста  
  - радиус поиска  

## Технологии:

- Python + FastAPI  
- PostgreSQL  
- SQLAlchemy / Alembic  
- Pydantic  
- MinIO (S3) для хранения фотографий  

---

#  Matching Module

Отвечает за логику знакомств и выдачу анкет.

## Функциональность:

- Формирование ленты анкет  
- Фильтрация пользователей по предпочтениям  
- Обработка действий:
  - лайк  
  - пропуск  
- Создание мэтча при взаимной симпатии  
- Подготовка данных для рейтинга  

## Технологии:

- Python (внутренний модуль)  
- Redis (кэширование ленты)  
- MQ (асинхронная обработка лайков и событий)  

---

#  Chat Module

Отвечает за обмен сообщениями между пользователями после мэтча.

## Функциональность:

- Отправка сообщений только при наличии мэтча  
- Получение истории переписки  
- Получение списка сообщений по диалогу  
- Хранение сообщений  

## Технологии:

- PostgreSQL  
- MQ (асинхронные события сообщений при необходимости)  

---

#  Rating Module

Отвечает за систему рейтингов пользователей.

## Функциональность:

- Трёхуровневая модель рейтинга:
  - первичный  
  - поведенческий  
  - итоговый  
- Обновление рейтинга на основе действий пользователей  
- Учет активности и взаимодействий  
- Влияние на выдачу анкет  

## Технологии:

- PostgreSQL  
- MQ (асинхронный пересчёт рейтингов)  

---

#  Background Jobs Module

Отвечает за выполнение фоновых задач системы.

## Функциональность:

- Пересчёт рейтингов пользователей  
- Обработка событий из MQ:
  - лайки  
  - мэтчи  
  - сообщения  
- Очистка и обновление данных  
- Выполнение отложенных задач  

## Технологии:

- Message Queue (основной механизм задач)  
- Celery (опционально)  
- Redis (broker при использовании Celery)  

---

#  Инфраструктурные компоненты

- **PostgreSQL** — основная база данных  
- **Redis** — кэширование и ускорение выдачи анкет  
- **MinIO (S3)** — хранение фотографий  
- **MQ (RabbitMQ / Kafka или аналог)** — асинхронные фоновые задачи внутри монолита  

---

#  Архитектурная схема

```mermaid
flowchart TD

    A[Telegram Bot] --> B[Monolith Application]

    subgraph Monolith Application

        B1[Users & Profiles Module]
        B2[Matching Module]
        B3[Chat Module]
        B4[Rating Module]
        B5[Background Jobs Module]
        MQ[(Message Queue)]

        B1 --> B2

        B2 -->|events: like / pass| MQ
        MQ --> B5

        B5 --> B4

        B2 -->|match created| B3

        B4 -->|rating update event| MQ
        MQ --> B5

    end

    B --> C[(PostgreSQL)]
    B --> D[(Redis)]
    B --> E[(MinIO S3)]
 ```

# Схема базы данных

```mermaid

erDiagram

    users {

        bigint id PK

        bigint telegram_id

        timestamp created_at

    }

    photos {

        bigint id PK

        bigint user_id FK

        string url

        boolean is_main

    }

    profiles {

        bigint id PK

        bigint user_id FK

        string name

        int age

        string gender

        text bio

        string city

    }

    preferences {

        bigint user_id PK,FK

        string preferred_gender

        int min_age

        int max_age


    }

    interactions {

        bigint id PK

        bigint from_user_id FK

        bigint to_user_id FK

        string action

        timestamp created_at

    }

    matches {

        bigint id PK

        bigint user1_id FK

        bigint user2_id FK

        timestamp created_at

    }

    messages {

        bigint id PK

        bigint match_id FK

        bigint sender_id FK

        text text

        timestamp created_at

        timestamp updated_at

    }

    ratings {

        bigint user_id PK,FK

        float primary_score

        float behavior_score

        float final_score

        timestamp updated_at

    }

    users ||--o{ photos : "has"

    users ||--|| profiles : "has"

    users ||--|| preferences : "has"

    users ||--o{ interactions : "from"

    users ||--o{ interactions : "to"

    users ||--o{ matches : "as user1"

    users ||--o{ matches : "as user2"

    users ||--o{ messages : "sends"

    users ||--|| ratings : "has"

    matches ||--o{ messages : "contains"