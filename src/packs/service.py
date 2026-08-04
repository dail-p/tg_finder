from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Channel, ChannelPack, PackChannel, User
from src.logging_setup import get_logger

log = get_logger(__name__)

MAX_PACKS_PER_USER = 50
MAX_CHANNELS_PER_PACK = 200


class PackLimitError(Exception):
    """Raised when a user hits a per-user/per-pack limit."""


class PackNameTakenError(Exception):
    """Raised when a pack name is not unique for the owner."""


class PackNotFoundError(Exception):
    """Raised when a pack does not exist or does not belong to the caller."""


class ChannelAlreadyInPackError(Exception):
    """Raised when adding a channel that is already in the pack."""


@dataclass(frozen=True)
class RemoveChannelResult:
    removed: bool
    pack_deleted: bool


async def get_or_create_user(
    session: AsyncSession,
    user_id: int,
    username: str | None = None,
) -> User:
    """Return the users row, creating it on first contact.

    Cheap happy path: a single SELECT by PK. On miss we INSERT; a concurrent
    insert would surface as IntegrityError, in which case we re-read.
    """
    user = await session.get(User, user_id)
    if user is not None:
        if username is not None and user.username != username:
            user.username = username
            await session.flush()
        return user

    user = User(id=user_id, username=username)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        user = await session.get(User, user_id)
        if user is None:  # pragma: no cover — race only
            raise
        if username is not None and user.username != username:
            user.username = username
            await session.flush()
    return user


async def list_packs(session: AsyncSession, owner_id: int) -> list[ChannelPack]:
    stmt = (
        select(ChannelPack)
        .where(ChannelPack.owner_id == owner_id)
        .order_by(ChannelPack.created_at, ChannelPack.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_pack(
    session: AsyncSession,
    pack_id: int,
    owner_id: int,
) -> ChannelPack | None:
    stmt = select(ChannelPack).where(
        ChannelPack.id == pack_id,
        ChannelPack.owner_id == owner_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_pack(
    session: AsyncSession,
    owner_id: int,
    name: str,
    description: str | None = None,
) -> ChannelPack:
    name = name.strip()
    if not name:
        raise ValueError("pack name must not be empty")

    existing = await list_packs(session, owner_id)
    if len(existing) >= MAX_PACKS_PER_USER:
        raise PackLimitError(f"max {MAX_PACKS_PER_USER} packs per user")
    if any(p.name == name for p in existing):
        raise PackNameTakenError(name)

    pack = ChannelPack(owner_id=owner_id, name=name, description=description)
    session.add(pack)
    await session.flush()
    log.info("pack.created", owner_id=owner_id, pack_id=pack.id, name=name)
    return pack


async def rename_pack(
    session: AsyncSession,
    pack_id: int,
    owner_id: int,
    name: str,
) -> ChannelPack:
    name = name.strip()
    if not name:
        raise ValueError("pack name must not be empty")
    pack = await get_pack(session, pack_id, owner_id)
    if pack is None:
        raise PackNotFoundError(str(pack_id))
    if pack.name == name:
        return pack
    # Uniqueness check against siblings.
    siblings = await list_packs(session, owner_id)
    if any(p.name == name and p.id != pack.id for p in siblings):
        raise PackNameTakenError(name)
    pack.name = name
    await session.flush()
    return pack


async def delete_pack(
    session: AsyncSession,
    pack_id: int,
    owner_id: int,
) -> bool:
    pack = await get_pack(session, pack_id, owner_id)
    if pack is None:
        return False
    await session.delete(pack)
    await session.flush()
    log.info("pack.deleted", owner_id=owner_id, pack_id=pack_id)
    return True


async def list_pack_channels(
    session: AsyncSession,
    pack_id: int,
    owner_id: int,
) -> list[Channel]:
    stmt = (
        select(Channel)
        .join(PackChannel, PackChannel.channel_id == Channel.id)
        .join(ChannelPack, ChannelPack.id == PackChannel.pack_id)
        .where(
            PackChannel.pack_id == pack_id,
            ChannelPack.owner_id == owner_id,
        )
        .order_by(Channel.title)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_pack_channel(
    session: AsyncSession,
    pack_id: int,
    channel_id: int,
    owner_id: int,
) -> Channel | None:
    stmt = (
        select(Channel)
        .join(PackChannel, PackChannel.channel_id == Channel.id)
        .join(ChannelPack, ChannelPack.id == PackChannel.pack_id)
        .where(
            Channel.id == channel_id,
            PackChannel.pack_id == pack_id,
            ChannelPack.owner_id == owner_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_pack_channel_ids(
    session: AsyncSession,
    pack_id: int,
    owner_id: int,
) -> list[int]:
    stmt = (
        select(PackChannel.channel_id)
        .join(ChannelPack, ChannelPack.id == PackChannel.pack_id)
        .where(
            PackChannel.pack_id == pack_id,
            ChannelPack.owner_id == owner_id,
        )
    )
    return [int(x) for x in (await session.execute(stmt)).scalars().all()]


async def get_user_channel_ids(session: AsyncSession, owner_id: int) -> list[int]:
    stmt = (
        select(PackChannel.channel_id)
        .join(ChannelPack, ChannelPack.id == PackChannel.pack_id)
        .where(ChannelPack.owner_id == owner_id)
        .distinct()
    )
    return [int(x) for x in (await session.execute(stmt)).scalars().all()]


async def _pack_size(session: AsyncSession, pack_id: int) -> int:
    stmt = select(PackChannel.channel_id).where(PackChannel.pack_id == pack_id)
    return len(list((await session.execute(stmt)).scalars().all()))


async def add_channel_to_pack(
    session: AsyncSession,
    pack_id: int,
    channel_id: int,
    owner_id: int,
) -> PackChannel:
    if await get_pack(session, pack_id, owner_id) is None:
        raise PackNotFoundError(str(pack_id))

    size = await _pack_size(session, pack_id)
    if size >= MAX_CHANNELS_PER_PACK:
        raise PackLimitError(f"max {MAX_CHANNELS_PER_PACK} channels per pack")

    existing = (
        await session.execute(
            select(PackChannel).where(
                PackChannel.pack_id == pack_id,
                PackChannel.channel_id == channel_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ChannelAlreadyInPackError(str(channel_id))

    link = PackChannel(pack_id=pack_id, channel_id=channel_id)
    session.add(link)
    await session.flush()
    return link


async def remove_channel_from_pack(
    session: AsyncSession,
    pack_id: int,
    channel_id: int,
    owner_id: int,
) -> RemoveChannelResult:
    pack = await get_pack(session, pack_id, owner_id)
    if pack is None:
        raise PackNotFoundError(str(pack_id))

    channel_ids = [
        int(value)
        for value in (
            await session.execute(
                select(PackChannel.channel_id).where(PackChannel.pack_id == pack_id)
            )
        )
        .scalars()
        .all()
    ]
    if channel_id not in channel_ids:
        return RemoveChannelResult(removed=False, pack_deleted=False)
    if len(channel_ids) == 1:
        await session.delete(pack)
        await session.flush()
        log.info("pack.deleted_empty", owner_id=owner_id, pack_id=pack_id)
        return RemoveChannelResult(removed=True, pack_deleted=True)

    result = await session.execute(
        delete(PackChannel).where(
            PackChannel.pack_id == pack_id,
            PackChannel.channel_id == channel_id,
        )
    )
    # result.rowcount on real SQLAlchemy; fakes may not expose it.
    rowcount = getattr(result, "rowcount", None)
    await session.flush()
    removed = bool(rowcount) if rowcount is not None else True
    return RemoveChannelResult(removed=removed, pack_deleted=False)


async def ensure_channel(
    session: AsyncSession,
    telegram_id: str,
    title: str | None = None,
    username: str | None = None,
) -> Channel:
    """Get or create a channels row, without indexing.

    Used when a user adds a channel from the bot: the scheduler's
    ``index_all_channels`` will pick it up on the next cycle. Until then the
    row exists with ``title == @username`` so the UI can show something.
    """
    telegram_id = telegram_id.strip()
    if not telegram_id:
        raise ValueError("telegram_id must not be empty")

    stmt = select(Channel).where(Channel.telegram_id == telegram_id)
    ch = (await session.execute(stmt)).scalar_one_or_none()
    if ch is not None:
        # Light touch-up: if we now know the username/title, record it.
        if username and ch.username != username:
            ch.username = username
        if title and ch.title == telegram_id and title != telegram_id:
            ch.title = title
        await session.flush()
        return ch

    ch = Channel(
        telegram_id=telegram_id,
        title=title or telegram_id,
        username=username,
    )
    session.add(ch)
    await session.flush()
    log.info("pack.channel_ensured", telegram_id=telegram_id, username=username)
    return ch


def normalize_username(raw: str) -> str | None:
    """Accept `@foo`, `https://t.me/foo`, `t.me/foo`, or bare `foo`; return `@foo` or None."""
    s = raw.strip()
    if not s:
        return None
    if s.startswith("@"):
        s = s[1:]
    elif s.lower().startswith("https://t.me/"):
        s = s[len("https://t.me/") :]
    elif s.lower().startswith("http://t.me/"):
        s = s[len("http://t.me/") :]
    elif s.lower().startswith("t.me/"):
        s = s[len("t.me/") :]
    s = s.strip().rstrip("/")
    if not s or "/" in s or " " in s:
        return None
    return f"@{s}"
