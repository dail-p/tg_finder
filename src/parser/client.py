from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import Message

from src.config import settings
from src.logging_setup import get_logger
from src.parser.models import ParsedPost

log = get_logger(__name__)


def get_telethon_client() -> TelegramClient:
    return TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        base_url=None if settings.openai_base_url.startswith("https://api.openai.com") else None,
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
    ) -> AsyncIterator[ParsedPost]:
        entity = await self.fetch_channel_entity(channel)
        offset_id = 0
        total = 0

        while total < self.history_limit:
            try:
                result = await self.client.get_messages(
                    entity,
                    limit=min(self.batch_size, self.history_limit - total),
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
