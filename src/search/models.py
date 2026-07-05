from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetrievedChunk:
    chunk_id: int
    post_id: int
    content: str
    similarity: float
    channel_title: str
    channel_telegram_id: str
    telegram_message_id: int

    def to_link(self) -> str:
        """Build a public Telegram link to the source post."""
        ref = self.channel_telegram_id
        # Public links work via @username when available.
        if ref.startswith("@"):
            return f"https://t.me/{ref[1:]}/{self.telegram_message_id}"
        if ref.startswith("-100"):
            return f"https://t.me/c/{ref[4:]}/{self.telegram_message_id}"
        return f"https://t.me/{ref}/{self.telegram_message_id}"
