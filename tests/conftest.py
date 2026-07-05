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

import random
from collections.abc import Sequence

import pytest

from src.config import Settings


@pytest.fixture()
def settings_instance() -> Settings:
    return Settings()  # type: ignore[call-arg]


def make_unit_vector(seed: int = 1, dim: int = 1536) -> list[float]:
    rng = random.Random(seed)
    vec = [rng.uniform(-1, 1) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


class FakeEmbeddings:
    """In-memory embeddings client that hashes text to a deterministic vector."""

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []
        # token -> known vector; populated by tests when needed.
        self._known: dict[str, list[float]] = {}

    def register(self, text: str, vec: list[float]) -> None:
        self._known[text] = vec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for t in texts:
            if t in self._known:
                out.append(self._known[t])
            else:
                out.append(make_unit_vector(hash(t) & 0xFFFF, self.dim))
        return out

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


@pytest.fixture()
def fake_embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()
