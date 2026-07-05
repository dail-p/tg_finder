FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
COPY main.py ./
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --upgrade pip && pip install .

ENV PYTHONPATH=/app

CMD ["python", "main.py"]
