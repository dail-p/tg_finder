from __future__ import annotations

import os

# Provide hermetic defaults before any `src` import (settings is a singleton
# built at import time and reads env/.env at construction).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.setdefault("ALLOWED_USER_IDS", "111,222")
os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "testhash")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import pytest

from src.config import Settings


@pytest.fixture()
def settings_instance() -> Settings:
    return Settings()  # type: ignore[call-arg]
