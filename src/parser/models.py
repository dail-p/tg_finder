from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.parser.extract import extract_hashtags, extract_title


def _to_naive_utc(dt: datetime | None) -> datetime | None:
    """Convert a datetime to a timezone-naive UTC value.

    Telethon returns timezone-aware datetimes (``message.date`` is UTC with a
    ``tzinfo``), but the DB schema uses naive ``TIMESTAMP WITHOUT TIME ZONE``
    columns. Mixing aware and naive values breaks asyncpg's codec with
    "can't subtract offset-naive and offset-aware datetimes", so we normalize
    to naive UTC at the parsing boundary.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


@dataclass
class ParsedPost:
    telegram_message_id: int
    content: str
    media_type: str
    posted_at: datetime | None
    title: str = ""
    hashtags: list[str] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    grouped_id: int | None = None

    def __post_init__(self) -> None:
        self.posted_at = _to_naive_utc(self.posted_at)
        # Derive title/hashtags from content unless passed explicitly.
        if not self.title:
            self.title = extract_title(self.content)
        if not self.hashtags:
            self.hashtags = extract_hashtags(self.content)

    @property
    def is_text(self) -> bool:
        return bool(self.content and self.content.strip())
