from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.db.models import Channel, Post, PostChunk
from src.indexer.chunker import chunk_text
from src.indexer.pipeline import _store_post, get_or_create_channel, index_channel
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
    commit_count: int = 0
    savepoint_rollbacks: int = 0

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
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rolled_back = True
        self.added.clear()

    def begin_nested(self) -> _Savepoint:
        """Simulate a SAVEPOINT: a rollback only discards the savepoint, not
        the outer transaction's committed/flushed rows."""
        return _Savepoint(self)


class _Savepoint:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self._session.savepoint_rollbacks += 1
        return False  # propagate exceptions to the caller's try/except


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


@dataclass
class FakeParser:
    """Stub TelethonParser: yields a fixed list of posts."""
    title: str = "News"
    username: str | None = "news"
    posts: list[ParsedPost] = field(default_factory=list)

    async def resolve_channel(self, channel: str) -> tuple[str, str | None]:
        return self.title, self.username

    async def iter_posts(self, channel: str, min_id: int = 0) -> AsyncIterator[ParsedPost]:
        for p in self.posts:
            if p.telegram_message_id > min_id:
                yield p


@pytest.mark.asyncio
async def test_index_channel_commits_channel_before_loop() -> None:
    """The channel must be persisted before indexing starts so a per-post
    failure can never trigger an FK violation on posts.channel_id."""
    session = FakeSession()
    session.set_scalar_returns(None)  # no existing channel

    parser = FakeParser(posts=[])
    embeddings = FakeEmbeddings()

    channel, created = await index_channel(
        session, parser, embeddings, "@news", incremental=False
    )
    assert channel.telegram_id == "@news"
    assert created == 0
    # commit() called once for the channel, once at the end of the loop.
    assert session.commit_count >= 1
    # No full rollback of the outer transaction.
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_index_channel_failed_post_does_not_wipe_channel() -> None:
    """Regression for the FK violation: a failing post (embedding error) must
    not roll back the channel, and subsequent posts must still be insertable
    with a valid channel_id reference."""
    session = FakeSession()
    # Channel: none existing.
    # Then for each post, _store_post does one execute() to check duplicates.
    session.set_scalar_returns(None, None, None)

    class FlakeyEmbeddings(FakeEmbeddings):
        def __init__(self) -> None:
            super().__init__()
            self._call = 0

        async def embed(self, texts):
            self._call += 1
            if self._call == 1:
                raise RuntimeError("transient openai error")
            return await super().embed(texts)

    embeddings = FlakeyEmbeddings()
    posts = [
        ParsedPost(telegram_message_id=1, content="упавший пост", media_type="text", posted_at=None),
        ParsedPost(telegram_message_id=2, content="хороший пост", media_type="text", posted_at=None),
    ]
    parser = FakeParser(posts=posts)

    channel, created = await index_channel(
        session, parser, embeddings, "@news", incremental=False
    )

    # Channel survived: it has a stable id and was committed before the loop.
    assert channel.id is not None
    assert session.commit_count >= 1
    # The failed post triggered a savepoint rollback, not a full rollback.
    assert session.savepoint_rollbacks == 1
    assert session.rolled_back is False
    # The second (successful) post was still inserted against the channel.
    assert created == 1
    inserted_posts = [o for o in session.added if isinstance(o, Post)]
    assert len(inserted_posts) == 1
    assert inserted_posts[0].channel_id == channel.id
    assert inserted_posts[0].telegram_message_id == 2
