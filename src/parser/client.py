from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import Message

from src.config import settings
from src.logging_setup import get_logger
from src.parser.models import ParsedPost

log = get_logger(__name__)


def get_telethon_client() -> TelegramClient:
    """Build a Telethon client.

    In production a pre-authorized ``TELEGRAM_SESSION_STRING`` is used so the
    client can connect non-interactively. When it is empty (local/dev) we fall
    back to a file-based session that can be authorized interactively.
    """
    session_string = settings.telegram_session_string.strip()
    session = (
        StringSession(session_string) if session_string else settings.telegram_session_name
    )
    return TelegramClient(
        session,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )


def _media_type(message: Message) -> str:
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.voice:
        return "voice"
    if message.sticker:
        return "sticker"
    return "text"


def _media_descriptors(message: Message) -> list[dict]:
    """Describe a message's attachment without downloading bytes.

    Telethon media objects differ per type, so every attribute is read via
    ``getattr`` with a default — a missing attribute must never raise here.
    """
    media = getattr(message, "media", None)
    if media is None:
        return []

    kind = _media_type(message)
    if kind == "text":
        return []

    descriptor: dict = {
        "kind": kind,
        "mime_type": None,
        "file_name": None,
        "width": None,
        "height": None,
        "size": None,
        "order": 0,
    }

    document = getattr(message, "document", None)
    if document is not None:
        descriptor["mime_type"] = getattr(document, "mime_type", None)
        descriptor["size"] = getattr(document, "size", None)
        for attr in getattr(document, "attributes", None) or []:
            width = getattr(attr, "w", None)
            height = getattr(attr, "h", None)
            if width is not None:
                descriptor["width"] = width
            if height is not None:
                descriptor["height"] = height
            file_name = getattr(attr, "file_name", None)
            if file_name is not None:
                descriptor["file_name"] = file_name
        return [descriptor]

    photo = getattr(message, "photo", None)
    if photo is not None:
        descriptor["mime_type"] = "image/jpeg"
        largest = None
        for size in getattr(photo, "sizes", None) or []:
            candidate_size = getattr(size, "size", None)
            if candidate_size is None:
                continue
            if largest is None or candidate_size > getattr(largest, "size", 0):
                largest = size
        if largest is not None:
            descriptor["width"] = getattr(largest, "w", None)
            descriptor["height"] = getattr(largest, "h", None)
            descriptor["size"] = getattr(largest, "size", None)

    return [descriptor]


class TelethonParser:
    """Iterates over a channel's history with FloodWait handling and batching."""

    def __init__(self, client: TelegramClient, history_limit: int | None = None) -> None:
        self.client = client
        self.history_limit = history_limit or settings.parser_history_limit
        self.batch_size = settings.parser_batch_size

    async def fetch_channel_entity(self, channel: str):
        return await self.client.get_entity(channel)

    async def iter_posts(
        self,
        channel: str,
        min_id: int = 0,
        *,
        limit: int | None = None,
    ) -> AsyncIterator[ParsedPost]:
        entity = await self.fetch_channel_entity(channel)
        offset_id = 0
        total = 0
        history_limit = self.history_limit if limit is None else min(self.history_limit, limit)

        while total < history_limit:
            try:
                result = await self.client.get_messages(
                    entity,
                    limit=min(self.batch_size, history_limit - total),
                    offset_id=offset_id,
                    min_id=min_id,
                )
            except FloodWaitError as exc:
                log.warning("telethon.flood_wait", seconds=exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
                continue

            if not result:
                break

            for message in result:
                if not isinstance(message, Message):
                    continue
                content = (message.message or "").strip()
                if not content and message.media is None:
                    continue
                yield ParsedPost(
                    telegram_message_id=message.id,
                    content=content or "",
                    media_type=_media_type(message),
                    posted_at=message.date,
                    media=_media_descriptors(message),
                    grouped_id=getattr(message, "grouped_id", None),
                )

            offset_id = result[-1].id
            total += len(result)
            if len(result) < self.batch_size:
                break

        log.info("telethon.parse_done", channel=channel, total=total)

    async def resolve_channel(self, channel: str) -> tuple[str, str | None]:
        """Return (title, username) for a channel reference."""
        entity = await self.fetch_channel_entity(channel)
        title = getattr(entity, "title", str(channel))
        username = getattr(entity, "username", None)
        return title, username

    async def get_last_message_id(self, channel: str) -> int:
        entity = await self.fetch_channel_entity(channel)
        result = await self.client.get_messages(entity, limit=1)
        if not result:
            return 0
        return int(result[0].id)
