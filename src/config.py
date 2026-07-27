from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram Bot
    bot_token: str = ""
    allowed_user_ids_str: str = Field("", alias="ALLOWED_USER_IDS")

    # Telethon
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_name: str = "tg_finder"
    telegram_session_string: str = ""

    # PostgreSQL
    database_url: str

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # Empty = fall back to llm_model. No concrete model is hardcoded here:
    # OPENAI_BASE_URL may point at a compatible proxy without that model.
    selector_model: str = ""
    answer_model: str = ""

    # Indexer / Parser
    parser_history_limit: int = 1000
    parser_batch_size: int = 100
    indexer_interval_minutes: int = 15
    title_max_len: int = 300

    # Retention (automatic cleanup of stale posts)
    post_retention_days: int = 180
    retention_interval_hours: int = 24

    # Search
    selector_token_budget: int = 30000
    selector_max_posts: int = 20000
    selector_max_selected: int = 15
    answer_token_budget: int = 12000
    answer_post_char_limit: int = 4000

    # Misc
    log_level: str = "INFO"
    environment: str = "dev"

    @property
    def allowed_user_ids(self) -> set[int]:
        if not self.allowed_user_ids_str.strip():
            return set()
        return {int(x.strip()) for x in self.allowed_user_ids_str.split(",") if x.strip()}

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def auth_enabled(self) -> bool:
        return bool(self.allowed_user_ids)

    @property
    def retention_enabled(self) -> bool:
        return self.post_retention_days > 0

    @property
    def selector_model_name(self) -> str:
        return self.selector_model.strip() or self.llm_model

    @property
    def answer_model_name(self) -> str:
        return self.answer_model.strip() or self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
