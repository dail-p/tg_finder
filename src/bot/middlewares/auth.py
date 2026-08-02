from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.logging_setup import get_logger
from src.packs.service import get_or_create_user


class AuthMiddleware(BaseMiddleware):
    """Allow only whitelisted users; ensure a users row exists on first contact.

    Auth runs *before* ``DbSessionMiddleware`` (outer), so to write the users
    row we open a short-lived session from the same factory rather than waiting
    for the per-handler one.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        log = get_logger(__name__)
        user = data.get("event_from_user")

        if user is None:
            return await handler(event, data)

        if settings.auth_enabled and user.id not in settings.allowed_user_ids:
            log.warning("auth.denied", user_id=user.id, username=user.username)
            if isinstance(event, Update):
                return
            try:
                await event.answer("⛔️ У вас нет доступа к этому боту.")  # type: ignore[attr-defined]
            except Exception:
                pass
            return

        if self.session_factory is not None:
            try:
                async with self.session_factory() as session:
                    await get_or_create_user(session, user.id, user.username)
                    await session.commit()
            except Exception as exc:
                log.error("auth.user_ensure_failed", user_id=user.id, error=str(exc))

        data["user_id"] = user.id
        return await handler(event, data)
