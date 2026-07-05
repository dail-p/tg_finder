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
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    llm_model: str = "gpt-4o-mini"

    # Indexer / Parser
    parser_history_limit: int = 1000
    parser_batch_size: int = 100
    chunk_size_tokens: int = 800
    chunk_overlap_tokens: int = 120
    embedding_batch_size: int = 64
    indexer_interval_minutes: int = 15

    # Search
    search_top_k: int = 10
    similarity_threshold: float = 0.35
    high_confidence: float = 0.7
    medium_confidence: float = 0.4

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
