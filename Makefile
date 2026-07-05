# Makefile for tg_finder
# Usage:
#   make install   — установить зависимости (включая dev)
#   make test      — прогнать юнит-тесты
#   make lint      — ruff
#   make typecheck — mypy
#   make local_db_up  — поднять локальную БД (pgvector) через docker compose
#   make local_db_down — остановить локальную БД
#   make migrate   — применить alembic-миграции к локальной БД
#   make check     — test + lint + typecheck одним вызовом

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
PYTEST := .venv/bin/python -m pytest
RUFF   := .venv/bin/ruff
MYPY   := .venv/bin/mypy
ALEMBIC := .venv/bin/alembic
COMPOSE := docker compose

DB_SERVICE := db
PG_USER    := tg_finder
PG_DB      := tg_finder

.DEFAULT_GOAL := help

.PHONY: help install test lint typecheck check local_db_up local_db_down migrate migrate-db healthcheck clean

help: ## Показать список команд
	@echo "Доступные цели:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости проекта (включая dev)
	$(PIP) install -e ".[dev]"

test: ## Прогнать юнит-тесты
	$(PYTEST) -q

test-cov: ## Прогнать тесты с покрытием
	$(PYTEST) --cov=src --cov-report=term-missing

lint: ## Линтинг ruff
	$(RUFF) check .

lint-fix: ## Автофикс ruff
	$(RUFF) check --fix .

typecheck: ## Проверка типов mypy
	$(MYPY) src tests

check: lint typecheck test ## lint + typecheck + test

# ===== Локальная БД (pgvector) =====

local_db_up: ## Поднять локальную БД с pgvector и убедиться, что расширение активно
	$(COMPOSE) up -d $(DB_SERVICE)
	@echo "Ожидание готовности БД..."
	@for i in $$(seq 1 30); do \
		$(COMPOSE) exec -T $(DB_SERVICE) pg_isready -U $(PG_USER) >/dev/null 2>&1 && break; \
		sleep 1; \
	done
	@$(COMPOSE) exec -T $(DB_SERVICE) psql -U $(PG_USER) -d $(PG_DB) \
		-c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
	@echo "Проверка расширения pgvector:"
	@$(COMPOSE) exec -T $(DB_SERVICE) psql -U $(PG_USER) -d $(PG_DB) \
		-c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

local_db_down: ## Остановить локальную БД
	$(COMPOSE) down

local_logs: ## Логи БД
	$(COMPOSE) logs -f $(DB_SERVICE)

migrate: local_up ## Применить alembic-миграции к локальной БД
	$(ALEMBIC) upgrade head
	@$(COMPOSE) exec -T $(DB_SERVICE) psql -U $(PG_USER) -d $(PG_DB) \
		-c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

healthcheck: ## Проверить состояние сервисов
	@$(COMPOSE) ps
	@$(COMPOSE) exec -T $(DB_SERVICE) pg_isready -U $(PG_USER)

clean: ## Удалить кэш pytest/ruff/mypy и __pycache__
	find . -type d -name __pycache__ -not -path './.kilo/*' -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache || true
