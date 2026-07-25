from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Channel, Post
from src.logging_setup import get_logger
from src.parser.client import TelethonParser
from src.parser.models import ParsedPost

log = get_logger(__name__)


async def get_or_create_channel(
    session: AsyncSession,
    telegram_id: str,
    title: str,
    username: str | None = None,
) -> Channel:
    stmt = select(Channel).where(Channel.telegram_id == telegram_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        if existing.title != title or existing.username != username:
            existing.title = title
            existing.username = username
            await session.flush()
        return existing
    ch = Channel(telegram_id=telegram_id, title=title, username=username)
    session.add(ch)
    await session.flush()
    return ch


async def _store_post(
    session: AsyncSession,
    channel: Channel,
    parsed: ParsedPost,
) -> bool:
    """Insert a post with its full text and media metadata. True if created."""
    existing = (
        await session.execute(
            select(Post.id).where(
                Post.channel_id == channel.id,
                Post.telegram_message_id == parsed.telegram_message_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    # Media-only posts are stored the same way, just with an empty title/content.
    post = Post(
        channel_id=channel.id,
        telegram_message_id=parsed.telegram_message_id,
        content=parsed.content or "",
        title=parsed.title,
        hashtags=list(parsed.hashtags),
        media=list(parsed.media),
        grouped_id=parsed.grouped_id,
        media_type=parsed.media_type,
        posted_at=parsed.posted_at,
    )
    session.add(post)
    await session.flush()
    return True


async def index_channel(
    session: AsyncSession,
    parser: TelethonParser,
    channel_ref: str,
    *,
    incremental: bool = True,
) -> tuple[Channel, int]:
    """Parse and index a single channel. Returns (Channel, posts_indexed)."""
    title, username = await parser.resolve_channel(channel_ref)
    telegram_id = str(channel_ref)
    channel = await get_or_create_channel(session, telegram_id, title, username)
    # Persist the channel row before the indexing loop so that a per-post
    # failure cannot wipe it (and the FK from posts -> channels stays valid).
    await session.commit()

    min_id = channel.last_indexed_message_id or 0 if incremental else 0

    log.info("indexer.start", channel=title, telegram_id=telegram_id, min_id=min_id)
    created = failed = 0
    max_msg_id = min_id

    async for post in parser.iter_posts(channel_ref, min_id=min_id):
        try:
            # Isolate each post in a SAVEPOINT so a failure only rolls back
            # that post, not the channel or previously committed posts.
            async with session.begin_nested():
                inserted = await _store_post(session, channel, post)
        except Exception as exc:
            log.error(
                "indexer.post_failed",
                channel=channel_ref,
                message_id=post.telegram_message_id,
                error=str(exc),
            )
            failed += 1
            continue
        if inserted:
            created += 1
        if post.telegram_message_id > max_msg_id:
            max_msg_id = post.telegram_message_id
        if created % 50 == 0 and created > 0:
            await session.commit()
            log.info("indexer.progress", channel=title, indexed=created, failed=failed)

    channel.last_indexed_message_id = max_msg_id
    await session.commit()
    log.info("indexer.done", channel=title, created=created, failed=failed)
    return channel, created


async def index_all_channels(
    session_factory,
    parser: TelethonParser,
) -> int:
    """Iterate over all channels stored in DB and refresh them."""
    from sqlalchemy import select

    from src.db.models import Channel as _Channel

    async with session_factory() as s:
        result = await s.execute(select(_Channel).order_by(_Channel.title))
        channels: Iterable[_Channel] = result.scalars().all()

    total = 0
    for ch in channels:
        ref = ch.username or ch.telegram_id
        async with session_factory() as s:
            try:
                _, created = await index_channel(s, parser, ref)
                total += created
            except Exception as exc:
                log.error("indexer.channel_failed", channel=ref, error=str(exc))
    return total
