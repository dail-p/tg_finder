from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ParsedPost:
    telegram_message_id: int
    content: str
    media_type: str
    posted_at: datetime | None

    @property
    def is_text(self) -> bool:
        return bool(self.content and self.content.strip())
