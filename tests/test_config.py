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
    assert s.llm_model == "gpt-4o-mini"
    assert s.indexer_interval_minutes == 15
    assert s.selector_token_budget == 30000
    assert s.selector_max_posts == 20000
    assert s.selector_max_selected == 15
    assert s.answer_token_budget == 12000
    assert s.answer_post_char_limit == 4000
    assert s.title_max_len == 300


def test_selector_and_answer_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("LLM_MODEL", "base-model")
    monkeypatch.setenv("SELECTOR_MODEL", "")
    monkeypatch.setenv("ANSWER_MODEL", "")
    s = Settings()  # type: ignore[call-arg]
    assert s.selector_model_name == "base-model"
    assert s.answer_model_name == "base-model"


def test_selector_and_answer_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h:5432/d")
    monkeypatch.setenv("LLM_MODEL", "base-model")
    monkeypatch.setenv("SELECTOR_MODEL", "sel-model")
    monkeypatch.setenv("ANSWER_MODEL", "ans-model")
    s = Settings()  # type: ignore[call-arg]
    assert s.selector_model_name == "sel-model"
    assert s.answer_model_name == "ans-model"
