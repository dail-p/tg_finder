from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI

from src.config import settings


@lru_cache
def get_llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
