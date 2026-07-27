from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.indexer.retention import (
    count_old_posts,
    prune_old_posts,
    retention_cutoff,
)


class _FakeDeleteResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    def scalar_one(self) -> int:
        return self.rowcount


@dataclass
class FakeSession:
    """Session stub returning a scripted rowcount per execute()."""

    rowcounts: list[int] = field(default_factory=list)
    executed: list = field(default_factory=list)
    commit_count: int = 0

    async def execute(self, stmt) -> _FakeDeleteResult:
        self.executed.append(stmt)
        rc = self.rowcounts.pop(0) if self.rowcounts else 0
        return _FakeDeleteResult(rc)

    async def commit(self) -> None:
        self.commit_count += 1


def test_retention_cutoff_is_now_minus_window() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    assert retention_cutoff(180, now=now) == now - timedelta(days=180)


@pytest.mark.asyncio
async def test_prune_deletes_and_commits() -> None:
    session = FakeSession(rowcounts=[7])
    deleted = await prune_old_posts(session, 180, batch_size=5000)
    assert deleted == 7
    assert session.commit_count == 1
    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_prune_batches_until_below_batch_size() -> None:
    session = FakeSession(rowcounts=[2, 2, 1])
    deleted = await prune_old_posts(session, 180, batch_size=2)
    assert deleted == 5
    assert len(session.executed) == 3
    assert session.commit_count == 3


@pytest.mark.asyncio
async def test_prune_noop_when_nothing_expired() -> None:
    session = FakeSession(rowcounts=[0])
    assert await prune_old_posts(session, 180, batch_size=2) == 0
    assert len(session.executed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [0, -1])
async def test_prune_disabled_touches_nothing(days: int) -> None:
    session = FakeSession(rowcounts=[100])
    assert await prune_old_posts(session, days) == 0
    assert session.executed == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_prune_falls_back_to_settings_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config import settings

    monkeypatch.setattr(settings, "post_retention_days", 0)
    session = FakeSession(rowcounts=[5])
    assert await prune_old_posts(session) == 0
    assert session.executed == []


@pytest.mark.asyncio
async def test_count_old_posts() -> None:
    session = FakeSession(rowcounts=[42])
    assert await count_old_posts(session, 180) == 42
    assert await count_old_posts(FakeSession(rowcounts=[42]), 0) == 0


def test_prune_sql_targets_posted_at_with_indexed_at_fallback() -> None:
    """The WHERE clause must expire NULL posted_at rows via indexed_at."""
    from sqlalchemy import delete, select

    from src.db.models import Post
    from src.indexer.retention import _expired

    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    sql = str(
        delete(Post).where(Post.id.in_(select(Post.id).where(_expired(cutoff)).scalar_subquery()))
    )
    assert "coalesce" in sql.lower()
    assert "posted_at" in sql
    assert "indexed_at" in sql
