from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SelectedPost:
    post_id: int
    title: str
    content: str
    hashtags: list[str]
    media: list[dict]
    channel_title: str
    channel_telegram_id: str
    telegram_message_id: int
    posted_at: datetime | None
    grouped_id: int | None = None
    album_media: list[dict] = field(default_factory=list)

    def to_link(self) -> str:
        """Build a public Telegram link to the source post."""
        ref = self.channel_telegram_id
        if ref.startswith("@"):
            return f"https://t.me/{ref[1:]}/{self.telegram_message_id}"
        if ref.startswith("-100"):
            return f"https://t.me/c/{ref[4:]}/{self.telegram_message_id}"
        return f"https://t.me/{ref}/{self.telegram_message_id}"

    def image_count(self) -> int:
        """Count photo attachments, including album neighbours."""
        items = list(self.media) + list(self.album_media)
        return sum(1 for m in items if isinstance(m, dict) and m.get("kind") == "photo")
