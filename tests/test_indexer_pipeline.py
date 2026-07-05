from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.db.models import Channel, Post, PostChunk
from src.indexer.chunker import chunk_text
from src.indexer.pipeline import _store_post, get_or_create_channel
from src.parser.models import ParsedPost
from tests.conftest import FakeEmbeddings, make_unit_vector


class _FakeScalars:
    def __init__(self, value: Any) -> None:
        self._value = value

    def all(self):
        return self._value if isinstance(self._value, list) else [self._value]

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._scalars = _FakeScalars(value)

    def scalar_one_or_none(self):
        return self._scalars.scalar_one_or_none()

    def scalars(self):
        return self._scalars

    def all(self):
        return self._scalars.all()


@dataclass
class FakeSession:
    """Minimal async session stub that assigns ids on flush."""

    _next_id: int = 1
    added: list = field(default_factory=list)
    committed: bool = False
    rolled_back: bool = False
    # Queue of return values for execute(...).scalar_one_or_none()
    _scalar_returns: list = field(default_factory=list)
    executed: list = field(default_factory=list)

    def set_scalar_returns(self, *values) -> None:
        self._scalar_returns = list(values)

    async def execute(self, stmt) -> _FakeResult:
        self.executed.append(stmt)
        val = self._scalar_returns.pop(0) if self._scalar_returns else None
        return _FakeResult(val)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None and hasattr(obj, "id"):
                obj.id = self._next_id
                self._next_id += 1

    async def commit(self) -> None:
        await self.flush()
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
        self.added.clear()


@pytest.mark.asyncio
async def test_get_or_create_channel_creates_new(fake_embeddings) -> None:
    session = FakeSession()
    session.set_scalar_returns(None)  # no existing channel
    ch = await get_or_create_channel(session, "@news", "News", "news")
    assert isinstance(ch, Channel)
    assert ch.telegram_id == "@news"
    assert ch.title == "News"
    assert ch.username == "news"
    assert ch in session.added


@pytest.mark.asyncio
async def test_get_or_create_channel_updates_existing() -> None:
    existing = Channel(id=5, telegram_id="@news", title="Old", username="old")
    session = FakeSession()
    session.set_scalar_returns(existing)
    ch = await get_or_create_channel(session, "@news", "News", "news")
    assert ch is existing
    assert ch.title == "News"
    assert ch.username == "news"
    assert session.added == []  # nothing added


@pytest.mark.asyncio
async def test_store_post_text_creates_post_and_chunks() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)  # no existing post
    embeddings = FakeEmbeddings()
    embeddings.register("контент", make_unit_vector(seed=7))

    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(
        telegram_message_id=42, content="контент", media_type="text", posted_at=None
    )

    created = await _store_post(session, channel, parsed, embeddings)
    assert created is True

    posts = [o for o in session.added if isinstance(o, Post)]
    chunks = [o for o in session.added if isinstance(o, PostChunk)]
    assert len(posts) == 1
    assert posts[0].telegram_message_id == 42
    # Number of chunks equals chunk_text output for "контент"
    expected_chunks = len(chunk_text("контент"))
    assert len(chunks) == expected_chunks
    assert all(c.embedding is not None for c in chunks)


@pytest.mark.asyncio
async def test_store_post_skips_existing() -> None:
    session = FakeSession()
    session.set_scalar_returns(99)  # existing post id
    embeddings = FakeEmbeddings()
    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(telegram_message_id=42, content="текст", media_type="text", posted_at=None)

    created = await _store_post(session, channel, parsed, embeddings)
    assert created is False
    assert session.added == []
    assert embeddings.calls == []  # no embedding calls for duplicate


@pytest.mark.asyncio
async def test_store_post_media_only_no_text_stores_metadata() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)
    embeddings = FakeEmbeddings()
    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(telegram_message_id=7, content="", media_type="photo", posted_at=None)

    created = await _store_post(session, channel, parsed, embeddings)
    assert created is True
    posts = [o for o in session.added if isinstance(o, Post)]
    assert len(posts) == 1
    assert posts[0].media_type == "photo"
    # No chunks created for empty text
    assert not any(isinstance(o, PostChunk) for o in session.added)
    assert embeddings.calls == []


@pytest.mark.asyncio
async def test_store_post_rolls_back_on_embedding_failure() -> None:
    class FailingEmbeddings(FakeEmbeddings):
        async def embed(self, texts):
            raise RuntimeError("openai error")

    session = FakeSession()
    session.set_scalar_returns(None)
    embeddings = FailingEmbeddings()
    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(telegram_message_id=1, content="текст", media_type="text", posted_at=None)

    with pytest.raises(RuntimeError):
        await _store_post(session, channel, parsed, embeddings)
