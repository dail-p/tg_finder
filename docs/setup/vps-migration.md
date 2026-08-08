# Переезд с Railway на VPS

Runbook для переноса `tg_finder` (bot + scheduler + Postgres) с Railway на свой VPS.
Вся подготовка уже сделана в коде: `docker-compose.yml` описывает целевую
архитектуру, скрипты в `scripts/` закрывают настройку сервера, деплой, бэкапы и
алерты. Ручной работы — примерно на 20 минут.

## Что упрощается по сравнению с Railway

Бот работает на long polling, входящего трафика нет вообще. Значит не нужны
домен, DNS, nginx, TLS-сертификаты, healthcheck-эндпоинты и открытые порты. VPS
должен уметь только исходящие соединения.

## Что нужно решить до старта

### 1. Геолокация VPS (блокирующее)

В `.env` стоит `OPENAI_BASE_URL=https://api.openai.com/v1` — прямой доступ к
OpenAI. Из российских дата-центров он не работает.

| Вариант | Плюсы | Минусы |
|---|---|---|
| VPS вне РФ (Hetzner, Contabo, Aeza EU, Vultr) | OpenAI и Telegram доступны напрямую, конфиг не меняется | оплата зарубежной картой |
| VPS в РФ + LLM-прокси | привычная оплата, низкий пинг до Telegram | лишнее звено, нужен `OPENAI_BASE_URL` на прокси и его аптайм |

Рекомендация: VPS вне РФ.

### 2. Переносить данные или начать с чистой базы

Без переноса дампа теряются пользователи, папки и каналы — их придётся создать
заново через `/folders`, после чего scheduler заново проиндексирует историю
(`PARSER_HISTORY_LIMIT` постов на канал). Посты как таковые не теряются: они
восстановимы из Telegram. Если папок немного, это дешевле, чем возиться с
дампом. Перенос описан в «Приложении A».

### 3. Размер машины

Минимум **2 vCPU / 4 GB RAM / 40 GB SSD**: Postgres с full-text индексом по
`content`, два python-процесса, селектор держит в памяти до
`SELECTOR_MAX_POSTS=20000` тайтлов на запрос, плюс сборка образа на этой же
машине. На 2 GB `pip install` при сборке упирается в память — `vps_bootstrap.sh`
поэтому создаёт swap.

## Что уже готово в коде

| Файл | Назначение |
|---|---|
| `docker-compose.yml` | Postgres на `127.0.0.1`, ротация логов, одноразовый сервис `migrate`, `restart: unless-stopped` у всех сервисов |
| `docker-entrypoint.sh` | `RUN_MIGRATIONS=0` отключает миграции в контейнере приложения |
| `scripts/vps_bootstrap.sh` | пользователь `deploy`, SSH-хардненинг, `ufw`, swap, Docker, автообновления |
| `scripts/deploy.sh` | проверка `.env`, `git pull`, сборка, миграции, старт, проверка что всё поднялось |
| `scripts/backup_db.sh` | `pg_dump -Fc` с ротацией и опциональной выгрузкой через rclone |
| `scripts/watchdog.sh` | алерт в Telegram про упавший контейнер, крэш-луп и заполнение диска |
| `scripts/install_cron.sh` | ставит cron-задания для бэкапа и watchdog |

Важное про compose: миграции выполняет отдельный сервис `migrate`
(`alembic upgrade head` и выход), а bot и scheduler ждут его через
`condition: service_completed_successfully`. Compose перезапускает `migrate` при
каждом `up -d`, так что новая миграция применяется на каждом деплое, и при этом
никогда не выполняется двумя контейнерами одновременно. Если миграция упала, bot
и scheduler не перезапускаются — продолжает работать старая версия.

## Этап 1. Подготовка сервера

```bash
ssh root@<ip>
curl -fsSL https://raw.githubusercontent.com/dail-p/tg_finder/main/scripts/vps_bootstrap.sh -o bootstrap.sh
bash bootstrap.sh
```

Скрипт идемпотентный. Он откажется работать, если в `/root/.ssh/authorized_keys`
нет ключа — иначе отключение парольной аутентификации закрыло бы доступ к
серверу. Сессию под root не закрывать, пока не проверен вход под `deploy`.

## Этап 2. Код и конфиг

```bash
ssh deploy@<ip>
git clone https://github.com/dail-p/tg_finder.git && cd tg_finder
cp .env.example .env && nano .env && chmod 600 .env
```

Значения переносятся из Railway → Variables. Что поменять относительно примера:

- `BOT_TOKEN`, `ALLOWED_USER_IDS`
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING` — строка
  сессии переносится как есть, повторная авторизация не нужна
- `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`, если через прокси)
- `POSTGRES_PASSWORD` — новый, не `tg_finder` из примера
- `ENVIRONMENT=prod`, `LOG_LEVEL=INFO`

`DATABASE_URL` и `APP_MODE` из файла не используются: compose подставляет свои
(хост `db`, режим на сервис). `deploy.sh` проверит заполненность обязательных
полей и предупредит про дефолтный пароль и пустой whitelist.

## Этап 3. Переключение

Порядок критичен. Один и тот же `BOT_TOKEN` в двух поллящих процессах даёт
`409 Conflict` в `getUpdates`, а одна `TELEGRAM_SESSION_STRING` с двух IP
одновременно — повод для Telegram убить сессию. Railway гасим **до** старта VPS.

```bash
# 1. Railway UI: остановить оба сервиса (bot и scheduler). Проект НЕ удалять.
# 2. если переносите данные — сейчас, до первого запуска (Приложение A)
# 3. на VPS:
./scripts/deploy.sh
```

`deploy.sh` соберёт образ, применит миграции, поднимет bot и scheduler и упадёт
с ненулевым кодом, если что-то из них не в состоянии `running`.

Приёмка:

- в логах `bot` — старт polling без трейсбеков;
- `/help` и `/folders` в боте отвечают;
- `/search` возвращает ответ со ссылками на источники;
- в логах `scheduler` в течение `INDEXER_INTERVAL_MINUTES` появляется цикл
  индексации; задание retention стартует сразу при запуске
  (`next_run_time=now`) — должно быть удаление старых постов или ноль
  удалённых, но не исключение.

```bash
docker compose logs -f --tail=50 bot scheduler
```

Ожидаемый простой: 10–20 минут между шагами 1 и 3.

## Этап 4. Бэкапы и алерты

```bash
./scripts/install_cron.sh              # бэкап в 04:00 + watchdog каждые 15 мин
./scripts/install_cron.sh --no-backup  # только watchdog
```

Проверить, что оба скрипта работают, не дожидаясь cron:

```bash
./scripts/backup_db.sh
./scripts/watchdog.sh
```

Бэкап на том же диске не спасает от смерти VPS. Для выгрузки наружу: поставить
`rclone`, настроить remote и указать `BACKUP_REMOTE=s3:bucket/tg_finder` в
`.env`. Раз в квартал проверять восстановление дампа локально — непроверенный
бэкап бэкапом не является.

Watchdog отправляет алерты через `BOT_TOKEN` в `ALERT_CHAT_ID` (по умолчанию —
первый id из `ALLOWED_USER_IDS`) и не спамит: повторное сообщение с тем же
набором проблем подавляется.

## Этап 5. Дальнейшие деплои

```bash
cd ~/tg_finder && ./scripts/deploy.sh
```

Когда надоест ходить по SSH — workflow на GitHub Actions: сборка образа, push в
GHCR, `ssh deploy@<ip> 'cd tg_finder && docker compose pull && docker compose up -d'`.
Потребует deploy-ключ в секретах репозитория и замену `build: .` на `image:` в
compose. Отдельная задача, к переезду не относится.

`railway.json` оставлен в репозитории намеренно — он нужен для откатного
сценария. Удалить, когда Railway-проект будет удалён.

## Откат

Railway-проект не удалять минимум неделю, только остановить сервисы. Если на VPS
что-то фундаментально не работает: `docker compose down` на VPS, запустить
сервисы в Railway обратно. Всё, что накопилось за время работы VPS (новые посты),
при откате теряется; папки и каналы, созданные за это время, придётся
пересоздать.

## Чеклист

- [ ] Выбран регион VPS с доступом к OpenAI и Telegram
- [ ] `vps_bootstrap.sh` выполнен, вход под `deploy` и `docker ps` проверены
- [ ] Репозиторий склонирован, `.env` заполнен, `chmod 600`, `ENVIRONMENT=prod`,
      новый `POSTGRES_PASSWORD`
- [ ] Railway остановлен **до** первого `deploy.sh`
- [ ] (Опционально) данные перенесены по Приложению A
- [ ] `deploy.sh` завершился успешно, все сервисы `running`
- [ ] Проверено: polling, `/folders`, `/search`, цикл индексации, retention
- [ ] `install_cron.sh` выполнен, `backup_db.sh` и `watchdog.sh` прогнаны вручную
- [ ] Railway-проект оставлен на неделю как путь отката

## Риски

| Риск | Митигация |
|---|---|
| Двойной polling одного токена → `409 Conflict` | Railway гасится до старта VPS (этап 3) |
| Две Telethon-сессии с одной строкой с разных IP | тот же порядок; scheduler на Railway тоже остановлен |
| Открытый Postgres на публичном IP | bind на `127.0.0.1` в compose, новый пароль, доступ через SSH-туннель |
| Гонка миграций между bot и scheduler | одноразовый сервис `migrate`, `RUN_MIGRATIONS=0` у приложений |
| Блокировка себе доступа при хардненинге SSH | `vps_bootstrap.sh` требует наличие ключа и валидирует конфиг через `sshd -t` |
| Диск заполнен логами или бэкапами | `max-size` у json-file, ротация в `backup_db.sh`, алерт по `df` в watchdog |
| Утечка `.env` | `chmod 600` (проверяется в `deploy.sh`), файл не коммитится, пароль БД меняется при переезде |
| Нет бэкапов после ухода с Railway | этап 4 — часть переезда, а не «потом» |

---

## Приложение A. Перенос данных с Railway

Выполнять между остановкой Railway и первым `deploy.sh`.

Сначала снять параметры источника (URL берётся из Railway, обязательно со схемой
`postgresql://`, не `postgresql+asyncpg://`):

```bash
export SRC_URL='postgresql://user:pass@host:port/railway'
psql "$SRC_URL" -c "select version();"
psql "$SRC_URL" -c "select pg_size_pretty(pg_database_size(current_database()));"
```

Мажорная версия PG на Railway должна совпадать с образом в compose
(`pgvector/pgvector:pg16`). Если там не 16 — поправить тег, иначе `pg_restore`
упрётся в несовместимость.

```bash
pg_dump --no-owner --no-privileges -Fc "$SRC_URL" -f tg_finder.dump
scp tg_finder.dump deploy@<ip>:~/
```

На VPS: сначала создать схему миграциями, потом залить только данные — так
`alembic_version` и структура остаются под контролем alembic.

```bash
cd ~/tg_finder
docker compose up -d db
docker compose up migrate                     # схема
docker compose exec -T db pg_restore --no-owner --no-privileges --data-only \
  -d tg_finder -U tg_finder \
  -t users -t channels -t channel_packs -t pack_channels -t posts \
  < ~/tg_finder.dump
./scripts/deploy.sh
```

Список таблиц указан явно, и это не перестраховка. В дампе лежит и
`alembic_version` — её данные при `--data-only` упрутся в primary key, потому что
alembic уже записал ту же ревизию. Плюс в старых базах остались таблицы прошлых
схем (например `post_chunks` от выпиленных эмбеддингов), которых в свежей схеме
нет, и `pg_restore` на них тоже отвалится. Пять таблиц выше — это вся актуальная
схема (`alembic/versions/0001_init.py`), при добавлении новых список надо
обновить.

Если restore жалуется на порядок foreign key — добавить `--disable-triggers`.

Проверка после заливки:

```bash
docker compose exec -T db psql -U tg_finder -d tg_finder \
  -c "select count(*) from posts;" -c "select count(*) from channel_packs;"
```

Образ базы остаётся `pgvector/pgvector:pg16`. Расширение `vector` в схеме не
используется (там только `to_tsvector('russian', ...)`), но образ совпадает с
локальным и CI — расхождение обошлось бы дороже, чем неиспользуемое расширение.
