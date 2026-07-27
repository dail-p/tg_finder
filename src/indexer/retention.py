from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Post
from src.logging_setup import get_logger

log = get_logger(__name__)

# Old posts are removed in chunks so a first run over a long-lived DB never
# builds one huge transaction (and never holds locks for minutes).
DELETE_BATCH_SIZE = 5000


def retention_cutoff(retention_days: int, *, now: datetime | None = None) -> datetime:
    """UTC timestamp before which posts are considered expired."""
    return (now or datetime.now(UTC)) - timedelta(days=retention_days)


def _expired(cutoff: datetime) -> ColumnElement[bool]:
    # posted_at is nullable (parse gaps / service messages) — fall back to the
    # moment we indexed the post so such rows still expire.
    return func.coalesce(Post.posted_at, Post.indexed_at) < cutoff


def _effective_days(retention_days: int | None) -> int:
    return settings.post_retention_days if retention_days is None else retention_days


async def count_old_posts(
    session: AsyncSession,
    retention_days: int | None = None,
    *,
    now: datetime | None = None,
) -> int:
    """How many posts are older than the retention window (0 when disabled)."""
    days = _effective_days(retention_days)
    if days <= 0:
        return 0
    stmt = (
        select(func.count()).select_from(Post).where(_expired(retention_cutoff(days, now=now)))
    )
    return int((await session.execute(stmt)).scalar_one() or 0)


async def prune_old_posts(
    session: AsyncSession,
    retention_days: int | None = None,
    *,
    now: datetime | None = None,
    batch_size: int = DELETE_BATCH_SIZE,
) -> int:
    """Delete posts older than the retention window. Returns the number deleted.

    ``retention_days <= 0`` disables pruning. Deleting posts is safe for
    incremental indexing: it tracks ``Channel.last_indexed_message_id``, which
    is untouched here, so pruned posts are not re-fetched.
    """
    days = _effective_days(retention_days)
    if days <= 0:
        log.info("retention.disabled")
        return 0

    cutoff = retention_cutoff(days, now=now)
    total = 0
    while True:
        batch = select(Post.id).where(_expired(cutoff)).limit(batch_size).scalar_subquery()
        # execute() is typed as returning Result; a DELETE always yields a
        # CursorResult, which is what carries rowcount.
        result = cast(
            CursorResult[Any],
            await session.execute(
                delete(Post).where(Post.id.in_(batch)).execution_options(synchronize_session=False)
            ),
        )
        deleted = result.rowcount or 0
        await session.commit()
        total += deleted
        if deleted < batch_size:
            break

    log.info(
        "retention.pruned",
        deleted=total,
        retention_days=days,
        cutoff=cutoff.isoformat(),
    )
    return total
