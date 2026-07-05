from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from src.config import settings
from src.logging_setup import get_logger


class AuthMiddleware(BaseMiddleware):
    """Allow only whitelisted users to interact with the bot."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        log = get_logger(__name__)
        user = data.get("event_from_user")

        if user is None:
            # Allow non-user events (e.g. inline queries handled separately) — but
            # for MVP we require a user.
            return await handler(event, data)

        if settings.auth_enabled and user.id not in settings.allowed_user_ids:
            log.warning("auth.denied", user_id=user.id, username=user.username)
            # For Message events we can answer; for callback_query we ignore.
            if isinstance(event, Update):
                # Should not happen: Update is wrapped at outer level.
                return
            try:
                await event.answer("⛔️ У вас нет доступа к этому боту.")  # type: ignore[attr-defined]
            except Exception:
                pass
            return

        data["user_id"] = user.id
        return await handler(event, data)
