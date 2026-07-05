from __future__ import annotations

import pytest

from src.config import Settings


def test_allowed_user_ids_parsed(settings_instance: Settings) -> None:
    assert settings_instance.allowed_user_ids == {111, 222}
    assert settings_instance.auth_enabled is True


def test_empty_allowed_list_disables_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    s = Settings()  # type: ignore[call-arg]
    assert s.allowed_user_ids == set()
    assert s.auth_enabled is False


def test_database_url_normalized_from_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    s = Settings()  # type: ignore[call-arg]
    assert s.database_url.startswith("postgresql+asyncpg://")


def test_database_url_kept_when_already_asyncpg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@host:5432/db")
    s = Settings()  # type: ignore[call-arg]
    assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"


def test_defaults_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("BOT_TOKEN", "x")
    s = Settings()  # type: ignore[call-arg]
    assert s.embedding_model == "text-embedding-3-small"
    assert s.embedding_dim == 1536
    assert s.llm_model == "gpt-4o-mini"
    assert s.indexer_interval_minutes == 15
    assert s.search_top_k == 10
