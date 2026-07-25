from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.db.models import Channel, Post
from src.indexer.pipeline import _store_post, get_or_create_channel, index_channel
from src.parser.models import ParsedPost


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
    _scalar_returns: list = field(default_factory=list)
    executed: list = field(default_factory=list)
    commit_count: int = 0
    savepoint_rollbacks: int = 0
    flush_fail_on: set[int] = field(default_factory=set)
    _flush_calls: int = 0

    def set_scalar_returns(self, *values) -> None:
        self._scalar_returns = list(values)

    async def execute(self, stmt) -> _FakeResult:
        self.executed.append(stmt)
        val = self._scalar_returns.pop(0) if self._scalar_returns else None
        return _FakeResult(val)

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self._flush_calls += 1
        if self._flush_calls in self.flush_fail_on:
            raise RuntimeError("flush failed")
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
        return _Savepoint(self)


class _Savepoint:
    def __init__(self, session: FakeSession) -> None:
        self._session = session
        self._added_len = 0

    async def __aenter__(self) -> _Savepoint:
        self._added_len = len(self._session.added)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self._session.savepoint_rollbacks += 1
            # Discard objects added inside the savepoint.
            del self._session.added[self._added_len :]
        return False


@pytest.mark.asyncio
async def test_get_or_create_channel_creates_new() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)
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
    assert session.added == []


@pytest.mark.asyncio
async def test_store_post_text_creates_post_with_title_and_hashtags() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)

    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(
        telegram_message_id=42,
        content="Заголовок поста\n\nТекст #AI #News",
        media_type="text",
        posted_at=None,
    )

    created = await _store_post(session, channel, parsed)
    assert created is True

    posts = [o for o in session.added if isinstance(o, Post)]
    assert len(posts) == 1
    assert posts[0].telegram_message_id == 42
    assert posts[0].title == "Заголовок поста"
    assert posts[0].hashtags == ["#ai", "#news"]
    assert posts[0].content.startswith("Заголовок поста")


@pytest.mark.asyncio
async def test_store_post_skips_existing() -> None:
    session = FakeSession()
    session.set_scalar_returns(99)
    channel = Channel(id=1, telegram_id="@news", title="News")
    parsed = ParsedPost(
        telegram_message_id=42, content="текст", media_type="text", posted_at=None
    )

    created = await _store_post(session, channel, parsed)
    assert created is False
    assert session.added == []


@pytest.mark.asyncio
async def test_store_post_media_only_no_text_stores_metadata() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)
    channel = Channel(id=1, telegram_id="@news", title="News")
    media = [
        {
            "kind": "photo",
            "mime_type": "image/jpeg",
            "file_name": None,
            "width": 100,
            "height": 80,
            "size": 1234,
            "order": 0,
        }
    ]
    parsed = ParsedPost(
        telegram_message_id=7,
        content="",
        media_type="photo",
        posted_at=None,
        media=media,
        grouped_id=999,
    )

    created = await _store_post(session, channel, parsed)
    assert created is True
    posts = [o for o in session.added if isinstance(o, Post)]
    assert len(posts) == 1
    assert posts[0].media_type == "photo"
    assert posts[0].title == ""
    assert posts[0].content == ""
    assert posts[0].media == media
    assert posts[0].grouped_id == 999


@dataclass
class FakeParser:
    title: str = "News"
    username: str | None = "news"
    posts: list[ParsedPost] = field(default_factory=list)

    async def resolve_channel(self, channel: str) -> tuple[str, str | None]:
        return self.title, self.username

    async def iter_posts(
        self,
        channel: str,
        min_id: int = 0,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ParsedPost]:
        yielded = 0
        for p in self.posts:
            if p.telegram_message_id <= min_id:
                continue
            yield p
            yielded += 1
            if limit is not None and yielded >= limit:
                break


@pytest.mark.asyncio
async def test_index_channel_commits_channel_before_loop() -> None:
    session = FakeSession()
    session.set_scalar_returns(None)

    parser = FakeParser(posts=[])

    channel, created = await index_channel(
        session, parser, "@news", incremental=False
    )
    assert channel.telegram_id == "@news"
    assert created == 0
    assert session.commit_count >= 1
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_index_channel_failed_post_does_not_wipe_channel() -> None:
    """A failing post (flush error) must not wipe the channel; later posts insert."""
    session = FakeSession()
    # Channel lookup, then per-post existence checks for msg 1 and 2.
    session.set_scalar_returns(None, None, None)
    # flush 1: channel create; flush 2: channel commit; flush 3: first post fails.
    session.flush_fail_on = {3}

    posts = [
        ParsedPost(
            telegram_message_id=1,
            content="упавший пост",
            media_type="text",
            posted_at=None,
        ),
        ParsedPost(
            telegram_message_id=2,
            content="хороший пост",
            media_type="text",
            posted_at=None,
        ),
    ]
    parser = FakeParser(posts=posts)

    channel, created = await index_channel(
        session, parser, "@news", incremental=False
    )

    assert channel.id is not None
    assert session.commit_count >= 1
    assert session.savepoint_rollbacks == 1
    assert session.rolled_back is False
    assert created == 1
    inserted_posts = [o for o in session.added if isinstance(o, Post)]
    assert len(inserted_posts) == 1
    assert inserted_posts[0].channel_id == channel.id
    assert inserted_posts[0].telegram_message_id == 2


@pytest.mark.asyncio
async def test_index_channel_respects_limit() -> None:
    session = FakeSession()
    # Channel lookup + existence checks for the two posts within the limit.
    session.set_scalar_returns(None, None, None)

    posts = [
        ParsedPost(
            telegram_message_id=i,
            content=f"post {i}",
            media_type="text",
            posted_at=None,
        )
        for i in range(1, 6)
    ]
    parser = FakeParser(posts=posts)

    channel, created = await index_channel(
        session, parser, "@news", incremental=False, limit=2
    )

    assert created == 2
    inserted = [o for o in session.added if isinstance(o, Post)]
    assert [p.telegram_message_id for p in inserted] == [1, 2]
    assert channel.last_indexed_message_id == 2
