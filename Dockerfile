FROM python:3.12-slim

# System deps: gcc + libpq for asyncpg/psycopg compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run the Telegram bot
CMD ["python", "main.py"]
