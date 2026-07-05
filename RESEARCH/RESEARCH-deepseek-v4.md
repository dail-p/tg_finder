# Telegram Bot: Умный поиск по каналам — Исследование архитектур и план работ

## Требования

| # | Требование | Критерий приёмки |
|---|-----------|-----------------|
| 1 | Ответ на вопрос по тематике канала | Бот агрегирует информацию из разных постов одного канала и даёт сводный ответ |
| 2 | Пачки каналов | Пользователь создаёт/редактирует группы каналов; поиск идёт только по выбранной пачке |
| 3 | Нет информации = честный ответ | Если релевантных данных не найдено, бот сообщает об этом, не выдумывая |
| 4 | Структурированный ответ + ссылки | Ответ содержит суть + список ссылок на посты-источники, а не сырую выдачу |

---

## Обзор архитектур поиска

### 1. RAG (Retrieval-Augmented Generation) — семантический поиск

```
Пользователь → Bot → Embedding(query) → Vector DB (top-k) → LLM → Ответ + ссылки
```

**Как работает:**
- Посты каналов чанкаются (по 512–1024 токенов), для каждого чанка считается embedding
- Embedding-модель (text-embedding-3-small / intfloat/multilingual-e5-large) → pgvector/Chroma/Qdrant
- При запросе: embedding вопроса → ANN-поиск → top-k чанков → промпт LLM → синтез ответа

**Сильные стороны:** понимает синонимы, перефразировки, обобщает разрозненные куски
**Слабые стороны:** галлюцинации, плохо ищет точные имена/даты/цифры, стоимость LLM

### 2. BM25 / Full-Text Search — ключевой поиск

```
Пользователь → Bot → Query parsing → PostgreSQL FTS/Elasticsearch → BM25-ranked → Ответ + ссылки
```

**Как работает:**
- Посты индексируются в PostgreSQL GIN-index (tsvector) или Elasticsearch
- При запросе: токенизация → BM25-ранжирование → порог релевантности → сборка ответа
- Без LLM: просто сниппеты постов со ссылками

**Сильные стороны:** отлично находит точные совпадения (имена, даты, цифры), дёшево, без галлюцинаций
**Слабые стороны:** не понимает синонимы ("суп солянка" ≠ "мясная сборная солянка"), нет семантики

### 3. Hybrid (BM25 + Vector + Reranker)

```
             ┌─→ BM25 (PostgreSQL FTS) ─┐
Пользователь ─┤                         ├─→ RRF fusion → Reranker → LLM → Ответ
             └─→ Vector (pgvector) ─────┘
```

**Как работает:**
- Параллельный поиск: BM25 + ANN-vector
- Reciprocal Rank Fusion (RRF) для объединения результатов
- Cross-encoder reranker (bge-reranker-v2-m3) переранжирует топ-10
- LLM синтезирует финальный ответ из топ-5 чанков

**Сильные стороны:** закрывает слабости обоих подходов, лучшая точность
**Слабые стороны:** сложнее инфраструктура, выше задержка, дороже

### 4. Agentic RAG — многошаговый поиск

```
Пользователь → Bot → Query decomposition → Multi-step retrieval → Synthesis → Ответ
                              │
                              ├─→ "какие ингредиенты для солянки?" → vector
                              ├─→ "рецепт приготовления солянки" → bm25
                              └─→ "сколько варить солянку?" → hybrid
```

**Как работает:**
- LLM-агент декомпозирует сложный вопрос на подзапросы
- Каждый подзапрос идёт своим путём (bm25/vector/hybrid)
- Результаты агрегируются и синтезируются

**Сильные стороны:** сложные multi-hop вопросы, максимальная полнота
**Слабые стороны:** самая высокая задержка и стоимость, overkill для MVP

---

## Стратегии обновления данных

### A. Периодический поллинг (cron/scheduler)

```
Каждые N минут → парсить все каналы → проверять новые посты → индексировать
```

- **Реализация:** Telethon client + AsyncIOScheduler
- **Плюсы:** просто, надёжно, не зависит от внешних событий
- **Минусы:** задержка между постом и индексацией (N минут), нагрузка даже когда нет новых постов

### B. Webhook / Event-driven (автообновление при постинге)

```
Новый пост в канале → Telegram не предоставляет webhook для этого (только для ботов)
                     → Альтернатива: MTProto-клиент слушает updates в реальном времени
```

- **Реализация:** Telethon с `client.add_event_handler()` на `NewMessage`
- **Плюсы:** мгновенная индексация, нет лишней нагрузки
- **Минусы:** нужно держать постоянное MTProto-соединение, сложнее обрабатывать переподключения

### C. Гибрид (рекомендовано)

```
MTProto listener (реалтайм) + fallback cron (раз в час полный рескан)
```

- Реалтайм-индексация через Telethon events
- Hourly cron для сверки пропущенных постов и полной переиндексации
- **Выбор для production:** A для MVP, C для финальной версии

---

## Сравнение архитектур

| Критерий | RAG | BM25 | Hybrid | Agentic |
|----------|-----|------|--------|---------|
| Точность (exact match) | 4/10 | 9/10 | 9/10 | 9/10 |
| Семантическое понимание | 9/10 | 3/10 | 9/10 | 10/10 |
| Multi-hop вопросы | 5/10 | 2/10 | 6/10 | 9/10 |
| Скорость ответа | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| Стоимость (API) | ★★★☆☆ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| Риск галлюцинаций | высокий | нулевой | низкий | средний |
| Сложность инфры | ★★★★☆ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| No-answer detection | LLM-based | threshold-based | confidence score | multi-step |

**Рекомендация:** начать с RAG (MVP), эволюционировать в Hybrid.

---

## Модель данных

```sql
-- Пользователи бота
CREATE TABLE users (
    id BIGINT PRIMARY KEY,          -- telegram user_id
    username TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Каналы (источники)
CREATE TABLE channels (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,       -- @channel username или chat_id
    title TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Пачки каналов
CREATE TABLE channel_packs (
    id BIGSERIAL PRIMARY KEY,
    owner_id BIGINT REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- M2M: пачка ↔ канал
CREATE TABLE pack_channels (
    pack_id BIGINT REFERENCES channel_packs(id) ON DELETE CASCADE,
    channel_id BIGINT REFERENCES channels(id) ON DELETE CASCADE,
    PRIMARY KEY (pack_id, channel_id)
);

-- Посты
CREATE TABLE posts (
    id BIGSERIAL PRIMARY KEY,
    channel_id BIGINT REFERENCES channels(id) ON DELETE CASCADE,
    telegram_message_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    media_type TEXT,                  -- 'text', 'photo', 'video', 'document'
    posted_at TIMESTAMPTZ,
    indexed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(channel_id, telegram_message_id)
);

-- Чанки постов (для векторного поиска)
CREATE TABLE post_chunks (
    id BIGSERIAL PRIMARY KEY,
    post_id BIGINT REFERENCES posts(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_count INT,
    embedding VECTOR(1536),           -- размерность зависит от модели
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Индекс для поиска
CREATE INDEX ON post_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_posts_content_fts ON posts USING GIN (to_tsvector('russian', content));
```

---

## План работ для субагентов

### Subagent 1: Инфраструктура и Bot Framework

**Задача:** базовая структура проекта, конфигурация, Telegram Bot API

1. Инициализация проекта: `pyproject.toml`, `poetry.lock`, `.env.example`, `.gitignore`, `Dockerfile`
2. Модуль конфигурации (`src/config.py`): Pydantic Settings, переменные окружения
3. Базовая структура aiogram бота: диспатчер, роутеры, middleware
4. Middleware для проверки авторизации (белый список user_id)
5. Команды `/start`, `/help`
6. Базовая интеграция с PostgreSQL (asyncpg/SQLAlchemy async)

**Стек:** Python 3.12, aiogram 3.x, Pydantic v2, SQLAlchemy 2.0 async, Alembic
**Артефакты:** `src/bot/`, `src/config.py`, `src/db/`, `alembic/`, `docker-compose.yml`

### Subagent 2: Парсер каналов и индексация

**Задача:** сбор постов из Telegram-каналов, ETL-пайплайн индексации

1. Telethon клиент: авторизация, session-файл, обработка FloodWait
2. Парсер каналов: сбор истории (limit, offset, дата) + обход media/альбомов
3. Чанкер: разбивка длинных постов на чанки (512–1024 токена), sliding window overlap
4. Embedding generator: OpenAI text-embedding-3-small API с rate limiting и батчингом
5. Пайплайн индексации: пост → чанки → embeddings → pgvector INSERT
6. CLI-команда для ручного добавления канала и запуска парсинга
7. AsyncIOScheduler для периодического обновления (MVP: каждые 15 минут)

**Стек:** Telethon, openai (embeddings), pgvector, APScheduler
**Артефакты:** `src/parser/`, `src/indexer/`, `src/chunker.py`

### Subagent 3: Поисковый движок

**Задача:** RAG-пайплайн: вопрос → поиск → LLM-ответ

1. Embedding query → pgvector ANN-search (cosine similarity, top-k=10)
2. LLM-промпт с контекстом: шаблон промпта с инструкцией «отвечай только на основе предоставленного контекста, если информации нет — скажи об этом»
3. Парсинг ответа LLM: извлечение ссылок, проверка что ответ не выдуман
4. Стриминг ответа в Telegram (если LLM поддерживает streaming)
5. Ответ с форматированием: Markdown, inline-ссылки на посты (t.me/c/...)
6. Команды: `/search <вопрос>`, `/search <пачка> <вопрос>`

**Стек:** openai, pgvector
**Артефакты:** `src/search/`, `src/prompts/`

### Subagent 4: Управление пачками каналов

**Задача:** CRUD для пачек каналов, фильтрация поиска

1. Команды: `/packs` (список), `/pack_create <имя>`, `/pack_add <имя_пачки> <канал>`, `/pack_remove`, `/pack_delete`
2. Репозиторий для пачек (SQLAlchemy)
3. Инлайн-клавиатура для выбора пачки при поиске
4. Фильтрация векторного поиска по пачке: JOIN post_chunks → posts → pack_channels
5. Инлайн-режим бота: `@bot pack_name query` → мгновенный поиск

**Стек:** aiogram inline keyboards, SQLAlchemy
**Артефакты:** `src/packs/`, `src/keyboards/`

### Subagent 5: Confidence scoring и обработка no-answer

**Задача:** определение уверенности ответа и обработка случаев "нет информации"

1. Confidence score на основе cosine similarity порога (threshold)
2. LLM self-check: попросить модель оценить свою уверенность (0–10)
3. Комбинированный скоринг: max(similarity_score) × LLM_confidence
4. High confidence (>0.7): отдаём ответ
5. Medium confidence (0.4–0.7): отвечаем + предупреждение «возможно, неполный ответ»
6. Low confidence (<0.4): «К сожалению, в выбранных каналах нет информации по вашему вопросу»
7. Предложение: «Попробуйте переформулировать или выберите другую пачку каналов»

**Стек:** numpy, pgvector distance
**Артефакты:** `src/confidence.py`, `src/prompts/self_check.py`

### Subagent 6: Деплой и мониторинг

**Задача:** production-ready контейнеризация и observability

1. Docker Compose: bot + PostgreSQL + pgvector + (опционально) Redis
2. Healthcheck'и для всех сервисов
3. Логирование: structlog, уровни, ротация
4. Prometheus metrics: latency поиска, количество запросов, ошибки
5. docker-compose для автозапуска
6. CI/CD: GitHub Actions — линтинг, тесты, сборка образа

**Стек:** Docker, structlog, Prometheus client, Sentry SDK
**Артефакты:** `docker-compose.yml`, `Dockerfile`, `src/logging.py`, `.github/workflows/`

---

## Порядок выполнения (стадийность)

```
Этап 1 (MVP):           Subagent 1 + Subagent 2 + Subagent 3
                        → Бот ищет по одному каналу через RAG
                        
Этап 2 (Пачки):         Subagent 4
                        → Группировка каналов, фильтрация поиска

Этап 3 (Качество):      Subagent 5  
                        → Confidence scoring, честные "не знаю"

Этап 4 (Production):    Subagent 6
                        → Деплой, мониторинг, CI/CD
```

---

## Альтернативные стеки (если без внешних API)

| Компонент | Основной стек | Альтернатива (self-hosted) |
|-----------|--------------|---------------------------|
| LLM | OpenAI GPT-4o-mini | llama.cpp с Qwen-2.5-7B / Mistral |
| Embeddings | text-embedding-3-small | intfloat/multilingual-e5-large (sentence-transformers) |
| Vector DB | pgvector | Chroma / Qdrant (embedded mode) |
| Reranker | Cohere Rerank | bge-reranker-v2-m3 (FlagEmbedding) |

---

## Оценка рисков

| Риск | Вероятность | Влияние | Митигация |
|------|------------|---------|-----------|
| FloodWait от Telegram API | высокая | среднее | Rate limiter, exponential backoff |
| Галлюцинации LLM | средняя | высокое | Confidence scoring, промпт-ограничения |
| Большие каналы (10k+ постов) | высокая | среднее | Пагинированный парсинг, batch indexing |
| Рост стоимости API | средняя | высокое | Кэширование embeddings, self-hosted fallback |
| MTProto-соединение обрывается | средняя | низкое | Auto-reconnect + cron fallback |
