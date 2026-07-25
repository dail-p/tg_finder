# Отказ от RAG: полные посты в БД + двухшаговый LLM-пайплайн

## Цель

Заменить векторный RAG (эмбеддинги + чанки + pgvector ANN) на прямое хранение
полных постов и двухшаговый отбор через LLM:

1. Пост целиком пишется в `posts` (текст + метаданные медиа).
2. При записи отдельно сохраняются `title` (первый абзац) и `hashtags`.
3. По запросу пользователя все заголовки уходят в модель-селектор одним
   запросом (с лимитом по токенам), она возвращает id релевантных постов.
4. Из выбранных постов собирается контекст и уходит в модель-ответчик.

## Принятые решения

| Вопрос | Решение |
| --- | --- |
| Хранение медиа | Только метаданные, байты не скачиваем |
| Показ картинок в ответе | Пометка «🖼 N» + ссылка на пост, без досылки файлов |
| Идентификаторы медиа (`id`/`access_hash`) | Не храним — их некому использовать |
| Масштаб отбора | Все заголовки, один LLM-запрос, обрезка по токен-бюджету (свежие первыми) |
| Модели | Две настройки: `SELECTOR_MODEL` + `ANSWER_MODEL` |
| Миграции | БД пустая → `0001_init.py` переписывается с нуля, `0002` не нужна |

## Что удаляется

| Файл / объект | Действие |
| --- | --- |
| `src/indexer/chunker.py` | удалить |
| `src/indexer/embeddings.py` | удалить |
| `src/search/retrieval.py` | удалить (`Retriever`) |
| `src/search/confidence.py` | удалить (`classify_confidence`, `ConfidenceLevel`) |
| `src/search/rag.py` | заменяется на `src/search/answerer.py` |
| `src/search/models.py` → `RetrievedChunk` | заменить на `SelectedPost` |
| `src/db/models.py` → `PostChunk` | удалить модель и `Post.chunks` |
| `pgvector` в `pyproject.toml` | убрать (`tiktoken` **оставить** — нужен для токен-бюджета) |
| `EmbeddingsClient` в `cli.py`, `pipeline.py`, `scheduler/tasks.py`, `bot/handlers/search.py` | убрать из сигнатур и вызовов |

`init_db()` (`src/db/session.py:33-35`) перестаёт делать
`CREATE EXTENSION vector` — остаётся только `create_all`.

Docker-образ БД (`docker-compose.yml:3`, `.github/workflows/ci.yml:14`)
оставляем `pgvector/pgvector:pg16` — это надмножество postgres, менять образ
не обязательно и это лишний риск для CI.

## Схема БД

### `posts` — новые колонки

```python
title: Mapped[str] = mapped_column(Text, default="", server_default="")
hashtags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # ["#ai", "#news"]
media: Mapped[list[dict]] = mapped_column(JSONB, default=list)
grouped_id: Mapped[int | None] = mapped_column(BigInteger)        # альбомы
```

`content` остаётся полным текстом поста (включая первый абзац и хештеги —
ничего не вырезаем, чтобы контекст для ответчика был целостным).

Формат элемента `media` — метаданные без байтов и без Telegram-идентификаторов:

```json
{
  "kind": "photo",
  "mime_type": "image/jpeg",
  "file_name": null,
  "width": 1280,
  "height": 720,
  "size": 154213,
  "order": 0
}
```

`kind` берётся из существующего `_media_type()` (`src/parser/client.py:36`).
`Post.media_type` сохраняется (тип первого медиа), `media` — полный список.

### Индексы

- `post_chunks` и её индексы (`ix_post_chunks_embedding_hnsw`,
  `ix_post_chunks_post_id`) в новой схеме отсутствуют;
- `idx_posts_content_fts` (GIN, `to_tsvector('russian', content)`) оставляем —
  задел на пре-фильтр, если токен-бюджет перестанет справляться;
- добавить `ix_posts_posted_at` (`posted_at DESC NULLS LAST`) — выборка
  заголовков по свежести для обрезки под бюджет;
- добавить `ix_posts_channel_posted_at` (`channel_id`, `posted_at DESC`) — для
  фильтра по каналам.

### Миграция: перезапись `alembic/versions/0001_init.py`

БД пустая и нигде не развёрнута, поэтому вторая миграция не нужна: `0001`
переписывается под финальную схему. `revision = "0001"`, `down_revision = None`
сохраняются.

Что меняется в файле:

1. Убрать `CREATE EXTENSION IF NOT EXISTS vector` (строка 26).
2. Убрать импорты `from pgvector.sqlalchemy import Vector` и
   `from src.config import settings` (строки 13, 16) — иначе `alembic upgrade
   head` требует удалённого пакета и завязывает DDL на env-переменную
   `EMBEDDING_DIM`.
3. Не создавать таблицу `post_chunks` и её индексы (строки 80-98).
4. В `posts` добавить `title`, `hashtags`, `media`, `grouped_id` с
   `server_default` (`''`, `'[]'::jsonb`, `'[]'::jsonb`, NULL).
5. Добавить два индекса по `posted_at`.
6. `downgrade()` — только дроп созданных таблиц/индексов, без `post_chunks`.

Бэкфилл `title` из `content` не нужен: данных нет.

Для любой уже существующей БД (если такая всё же найдётся) путь один: дропнуть
схему и накатить `0001` заново. Это следствие принятого решения; инкрементальной
миграции со `0001` на новую схему не будет.

## Парсинг: заголовок, хештеги, медиа

Новый модуль `src/parser/extract.py`:

```python
HASHTAG_RE = re.compile(r"(?<!\w)#([^\W\d_][\w_]{0,63})", re.UNICODE)

def extract_title(content: str, max_len: int | None = None) -> str: ...
def extract_hashtags(content: str) -> list[str]: ...
```

`extract_title`:

- абзацы делим по двум и более переводам строки (`\n\s*\n`);
- берём первый непустой абзац, внутренние одиночные `\n` схлопываем в пробел;
- если абзац состоит только из хештегов, emoji и пунктуации — берём следующий
  непустой (частый паттерн: шапка из тегов перед текстом);
- если абзацев нет (текст в одну строку) — берём первую строку;
- обрезаем по `max_len` (дефолт `settings.title_max_len`) по границе слова,
  добавляем `…`;
- пустой текст (медиа без подписи) → `""`.

`extract_hashtags`: уникальные, в порядке появления, нижний регистр, храним с
`#`.

`ParsedPost` (`src/parser/models.py:24`) расширяется полями `title: str = ""`,
`hashtags: list[str] = field(default_factory=list)`,
`media: list[dict] = field(default_factory=list)`, `grouped_id: int | None = None`.
`title`/`hashtags` вычисляются в `__post_init__` из `content`, если не переданы
явно — существующие позиционные вызовы в тестах не ломаются.

`TelethonParser.iter_posts` (`src/parser/client.py:61`) начинает собирать медиа.
Добавляется `_media_descriptors(message) -> list[dict]`: читает
`message.photo` / `message.document` (`mime_type`, `size`, атрибуты
`DocumentAttributeImageSize`, `DocumentAttributeFilename`) и `message.grouped_id`.
Всё через `getattr` с дефолтами — структура Telethon-объектов различается по
типам медиа, падать на отсутствующем атрибуте нельзя.

Альбомы (несколько сообщений с одним `grouped_id`) сохраняем **как отдельные
посты** с общим `grouped_id`. Слияние на этапе парсинга требовало бы буферизации
и ломало бы `uq_post_channel_msg`; вместо этого альбомы склеиваются при сборке
контекста.

## Индексация

`src/indexer/pipeline.py`:

- `_store_post(session, channel, parsed)` — параметр `embeddings` убирается,
  чанки и вызовы эмбеддингов удаляются;
- посты без текста больше не особый случай (`pipeline.py:56-67`): пишем такой
  же `Post` с `title=""`, `content=""` и заполненным `media`;
- убирается ветка `if not chunks: return False` (`pipeline.py:70-71`) — раньше
  пост мог потеряться, если чанкер вернул пустой список;
- `index_channel` / `index_all_channels` — убрать параметр `embeddings`. Логика
  savepoint-ов (`pipeline.py:125`) и коммита канала до цикла (`pipeline.py:113`)
  сохраняется без изменений;
- дозаполнения существующих постов не делаем: база пустая, ветка «обновить
  пустые поля» — лишний код.

`src/indexer/cli.py:42-46` и `src/scheduler/tasks.py:24` теряют создание
`EmbeddingsClient`.

## Поиск: шаг 1 — отбор по заголовкам

Новый `src/search/selector.py`.

```python
@dataclass
class TitleCandidate:
    post_id: int
    title: str
    hashtags: list[str]
    channel_title: str
    posted_at: datetime | None
```

`TitleSelector.select(session, question, channel_ids=None) -> list[int]`:

1. `SELECT posts.id, posts.title, posts.hashtags, posts.posted_at, channels.title`
   `FROM posts JOIN channels WHERE posts.title <> ''`
   `ORDER BY posts.posted_at DESC NULLS LAST`, опциональный фильтр по
   `channel_ids`, hard cap `selector_max_posts` (страховка от OOM).
2. Обрезка под `selector_token_budget`: строки формата
   `<id> | <канал> | <YYYY-MM-DD> | <title> | <хештеги>` считаются через
   `tiktoken` (кодировщик для `selector_model`, фолбэк `cl100k_base`), свежие
   включаются первыми. Число отброшенных логируется как `selector.truncated`,
   чтобы просадка охвата была видна в логах, а не только в качестве ответов.
3. Один вызов `chat.completions.create`: `SELECTOR_MODEL`, `temperature=0`,
   `response_format={"type": "json_object"}`. Ожидаемый ответ:
   `{"post_ids": [12, 45, 78]}`.
4. Парсинг: `json.loads`, фильтрация по множеству фактически показанных id
   (защита от галлюцинаций), обрезка до `selector_max_selected`. При ошибке
   сети/парсинга — логируем и возвращаем `[]` (→ честный «нет информации»),
   хендлер не падает.

Промпт селектора — новый `src/prompts/select.py`:

```
Ты отбираешь посты по теме вопроса. Тебе дан список заголовков в формате
"id | канал | дата | заголовок | хештеги". Верни СТРОГО JSON
{"post_ids": [...]} с id постов, которые могут содержать ответ.
Не придумывай id, используй только те, что есть в списке.
Если подходящих нет — верни {"post_ids": []}.
Лучше включить сомнительный пост, чем пропустить релевантный.
```

Медиа-посты без подписи (`title = ''`) в отбор не попадают. Это осознанно:
искать в них нечего, текста у них нет. При этом в БД они лежат и доступны через
ссылку на канал.

## Поиск: шаг 2 — генерация ответа

`src/search/models.py`: `RetrievedChunk` → `SelectedPost`:

```python
@dataclass
class SelectedPost:
    post_id: int
    title: str
    content: str
    hashtags: list[str]
    media: list[dict]
    channel_title: str
    channel_telegram_id: str
    telegram_message_id: int
    posted_at: datetime | None

    def to_link(self) -> str: ...      # логика RetrievedChunk.to_link() без изменений
    def image_count(self) -> int: ...  # len(media с kind == "photo")
```

`image_count` считает только `kind == "photo"`: видео и документы под пометкой
«🖼 N» показывать нельзя, это было бы вранье в UI. Если понадобится общая
пометка по всем вложениям — это отдельное поле, не переиспользование этого.

`src/search/answerer.py` — `PostAnswerer.answer(session, question, channel_ids=None)`:

1. `ids = await selector.select(...)`; пусто → `SearchAnswer(no_answer=True)` с
   текстом «К сожалению, в проиндексированных каналах нет информации по вашему
   вопросу.»
2. Загрузка полных постов: `WHERE posts.id IN ids` + join `channels`. Порядок
   восстанавливаем по порядку `ids` (модель ставит релевантные первыми, SQL этот
   порядок не сохраняет).
3. Склейка альбомов. Важно: в отбор попадает только та часть альбома, у которой
   есть подпись (у остальных `title = ''`, селектор их не видит). Поэтому
   склейка — это **дополнительный запрос за соседями**, а не группировка
   выбранных id:
   `SELECT id, media, telegram_message_id FROM posts WHERE grouped_id IN (<непустые grouped_id выбранных постов>)`.
   Медиа соседей добавляются к элементу контекста, ссылка остаётся на сообщение
   с текстом. Если у выбранных постов нет `grouped_id`, запрос не делается.
4. Бюджет контекста: посты добавляются пока сумма токенов `< answer_token_budget`;
   пост длиннее `answer_post_char_limit` обрезается по границе абзаца.
5. Один вызов `chat.completions.create`: `ANSWER_MODEL`, `temperature=0.2`.
   Fallback на список ссылок при ошибке LLM (`rag.py:73-82`) сохраняем.

`SearchAnswer` теряет `confidence: float` и `level: str` (уходят вместе с
`confidence.py`), остаются `text`, `sources: list[SelectedPost]`, `no_answer`.
`no_answer` определяется двумя явными условиями: пустой отбор селектора или
маркер `NO_ANSWER` в первой строке ответа модели. Substring-хак
`"нет информации" in text.lower()` (`rag.py:84-86`) убираем — он зависел от
формулировки модели.

`answer_streaming` (`rag.py:97-138`) удаляем: не вызывается ниоткуда и по факту
не стримит (собирает все дельты перед единственным `yield`).

Промпт ответчика `src/prompts/answer.py` переписывается под полные посты:
блоки `[i] <Канал> (<дата>) — <заголовок>` + полный текст + `Ссылка: <url>`, и
`[изображений: N]` для постов с фото. Правило про Markdown-ссылки убираем —
бот отправляет HTML и сам рисует список источников (`search.py:22-24`).
Добавляем правило: при отсутствии данных первая строка ответа — `NO_ANSWER`.

## Бот

`src/bot/handlers/search.py`:

- вместо `EmbeddingsClient` + `Retriever` + `RAGAnswerer` — `TitleSelector` +
  `PostAnswerer`;
- клиент OpenAI выносится в `src/search/llm.py` (`get_llm_client()` с
  `lru_cache`): сейчас `search.py:46-48` создаёт `AsyncOpenAI` на каждый
  `/search`;
- `_format_answer` теряет блок confidence (`search.py:25-30`); источники
  получают заголовок и пометку картинок:
  `1. <a href="link">Канал — Заголовок</a> 🖼 3`.

Остальные хендлеры и middleware не затрагиваются. Команда добавления канала
из бота не появляется — индексация по-прежнему через `tg-finder-index add`.

## Конфигурация

Добавляется в `src/config.py` и `.env.example`:

```
# Пусто = взять LLM_MODEL. Отбор дешевле держать на модели попроще,
# генерацию ответа — на модели посильнее (например ANSWER_MODEL=gpt-4o).
SELECTOR_MODEL=
ANSWER_MODEL=
SELECTOR_TOKEN_BUDGET=30000     # лимит токенов на список заголовков
SELECTOR_MAX_POSTS=20000        # hard cap на выборку из БД
SELECTOR_MAX_SELECTED=15        # сколько постов максимум идёт в контекст
ANSWER_TOKEN_BUDGET=12000       # лимит контекста для ответчика
ANSWER_POST_CHAR_LIMIT=4000     # обрезка одного очень длинного поста
TITLE_MAX_LEN=300
```

Дефолты `SELECTOR_MODEL`/`ANSWER_MODEL` — **пустая строка**, при пустом значении
берётся `llm_model`. Конкретные модели в дефолты не зашиваем: в текущем `.env`
`OPENAI_BASE_URL=https://api.openai.com/v1` и `LLM_MODEL=gpt-4o-mini`, но
`OPENAI_BASE_URL` может указывать на совместимый прокси, где `gpt-4o` просто нет,
и хардкод дефолта сломал бы такую установку. Рекомендация «поставить модель
посильнее в `ANSWER_MODEL`» живёт комментарием в `.env.example`.

Реализовать фолбэк как `@property` (`selector_model_name`, `answer_model_name`),
а не через валидатор: меньше магии в настройках, проще тестировать.

Удаляются: `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `CHUNK_SIZE_TOKENS`,
`CHUNK_OVERLAP_TOKENS`, `EMBEDDING_BATCH_SIZE`, `SIMILARITY_THRESHOLD`,
`HIGH_CONFIDENCE`, `MEDIUM_CONFIDENCE`, `SEARCH_TOP_K` (его роль переходит к
`SELECTOR_MAX_SELECTED`). Благодаря `extra="ignore"` (`config.py:13`) устаревшие
переменные в чужих `.env` не вызовут ошибку.

## Тесты

Удалить: `tests/test_chunker.py`, `tests/test_confidence.py`,
`tests/test_retriever.py`, `tests/test_rag.py`, а также `FakeEmbeddings` и
`make_unit_vector` из `tests/conftest.py`.

Обновить:

- `tests/test_indexer_pipeline.py` — убрать `embeddings` из вызовов
  `_store_post` / `index_channel`; «медиа без текста» проверяет запись `media` и
  пустой `title`; savepoint-регрессию (`test_index_channel_failed_post_does_not_wipe_channel`)
  переписать на падение в `session.flush()` — эмбеддингов больше нет, но
  изоляция поста savepoint-ом остаётся и должна тестироваться;
- `tests/test_parser_models.py` — `title`/`hashtags`/`media`/`grouped_id` в
  `ParsedPost`;
- `tests/test_prompts.py` — новый формат контекста + `NO_ANSWER`;
- `tests/test_search_handler.py` — `SearchAnswer` без confidence, пометка 🖼;
- `tests/test_config.py` — новые поля и фолбэк на `llm_model`;
- `tests/test_search_models.py` — `SelectedPost.to_link()` (`@username`,
  `-100...`, plain) + `image_count`.

Добавить:

- `tests/test_extract.py` — заголовок из первого абзаца; абзац из одних
  хештегов пропускается; текст в одну строку; пустой текст; обрезка по
  `TITLE_MAX_LEN` по границе слова; регистр и дедупликация хештегов; кириллица;
- `tests/test_selector.py` — формат строк списка; обрезка по токен-бюджету
  (при маленьком бюджете остаются самые свежие); парсинг JSON; отбрасывание
  id, которых не было в списке; `[]` при ошибке LLM и при невалидном JSON;
- `tests/test_answerer.py` — пустой отбор → `no_answer`; порядок постов как у
  селектора (не как у SQL); склейка альбома, где выбран только пост с подписью,
  а медиа соседей подтягиваются вторым запросом; отсутствие второго запроса,
  когда ни у одного выбранного поста нет `grouped_id`; соблюдение
  `ANSWER_TOKEN_BUDGET`; fallback при ошибке LLM; распознавание маркера
  `NO_ANSWER`.

## Документация

- `README.md` — раздел про RAG/эмбеддинги заменить описанием двухшагового
  пайплайна; убрать pgvector из описания поиска и требований;
- `pyproject.toml:8` — description «smart search across channel posts via RAG»
  переформулировать без RAG;
- `.env.example` — синхронизировать с новыми настройками.

## Порядок реализации

1. `src/parser/extract.py` + расширение `ParsedPost` + `tests/test_extract.py`.
2. Медиа-дескрипторы и `grouped_id` в `TelethonParser`.
3. Модель `Post` (новые колонки), удаление `PostChunk`, перезапись
   `alembic/versions/0001_init.py` под финальную схему без pgvector.
4. `pipeline.py` / `cli.py` / `scheduler/tasks.py` без эмбеддингов; удалить
   `chunker.py`, `embeddings.py`; `init_db()` без `CREATE EXTENSION`.
5. `src/search/llm.py`, `src/search/selector.py`, `src/prompts/select.py`.
6. `src/search/answerer.py`, новый `src/prompts/answer.py`, `SelectedPost`;
   удалить `rag.py`, `retrieval.py`, `confidence.py`.
7. `bot/handlers/search.py`, `src/config.py`, `.env.example`.
8. Тесты: удалить / обновить / добавить.
9. Валидация (см. ниже).

## Валидация

- `make lint && make typecheck && make test` — всё зелёное.
- `make local_db_up`, затем `.venv/bin/alembic upgrade head` на чистой БД:
  переписанный `0001` должен примениться без пакета `pgvector` в окружении.
  Проверить `\d posts` — есть `title`, `hashtags`, `media`, `grouped_id`;
  таблицы `post_chunks` нет.
- `.venv/bin/alembic downgrade base` — проходит без ошибок.
- Проверить, что `pgvector` реально не нужен: `pip uninstall pgvector` в venv,
  затем `alembic upgrade head` и `make test`.
- Живой прогон на одном канале: `tg-finder-index add @<channel> --full`, затем
  в БД убедиться, что `title` заполнен у текстовых постов, `hashtags` —
  у постов с тегами, `media` — у постов с фото, `grouped_id` — у альбомов.
- Один `/search` в боте: в логах два LLM-вызова (селектор + ответчик), в ответе
  список источников с заголовками.

## Вне объёма

Сознательно не трогаем в этой задаче:

- **Фильтр по каналам.** `channel_ids` остаётся в сигнатурах `TitleSelector` и
  `PostAnswerer`, но бот его не передаёт — как и сейчас с `Retriever`. Вместе с
  ним без применения остаются `channel_packs` / `pack_channels` и индекс
  `ix_posts_channel_posted_at`. Индекс всё равно создаём: он нужен ровно тогда,
  когда фильтр включат, и стоит дешево.
- **Два пути создания схемы.** `init_db()` (`create_all`) и Alembic по-прежнему
  дублируют друг друга, и `create_all` даёт naive `TIMESTAMP` против
  `TIMESTAMP WITH TIME ZONE` из миграции. Расхождение существующее, к отказу от
  RAG не относится.
- **Пре-фильтр через FTS** перед селектором. Индекс сохраняем, код не пишем.
- **Стриминг ответа** в Telegram. `answer_streaming` удаляется, замены нет.
- **Команда добавления канала из бота.** Только `tg-finder-index add`.
- **`ALLOWED_USER_IDS` пустой = доступ всем** (`config.py:68`). Отдельный вопрос
  безопасности, не смешиваем с этой переработкой.

## Что ломается и на что обратить внимание

- **Схема пересоздаётся, а не миграцируется.** Решение опирается на то, что БД
  пустая. Если к моменту реализации в какой-либо БД окажется
  `alembic_version = 0001` со старой схемой, её нужно дропнуть вручную —
  инкрементального пути не будет.
- **Стоимость запроса меняется по характеру.** Раньше: дешёвый эмбеддинг + один
  LLM-вызов на ~10 чанков. Теперь: два LLM-вызова, первый — с пачкой заголовков
  до 30k токенов. Растёт и латентность (два последовательных вызова).
- **Молчаливая потеря охвата при росте базы.** При числе постов, чьи заголовки
  не влезают в `SELECTOR_TOKEN_BUDGET`, старые посты выпадают из отбора. Это
  принятый компромисс; объём отсечения логируется (`selector.truncated`).
  Если станет проблемой — включить пре-фильтр через уже существующий
  `idx_posts_content_fts`.
- **`confidence` исчезает из UX.** Плашки «Высокая/Низкая уверенность»
  наполнять больше нечем: числового similarity нет.
- **Качество отбора зависит от качества заголовков.** Первый абзац — не всегда
  информативная тема поста; посты, где суть в середине текста, селектор может
  пропустить, потому что полный текст он не видит.
