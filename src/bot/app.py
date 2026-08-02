from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.handlers import base_router, folders_router, search_router
from src.bot.middlewares.auth import AuthMiddleware
from src.bot.middlewares.db import DbSessionMiddleware
from src.config import settings
from src.db.session import session_factory

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())

# Order matters: auth -> db. Auth opens its own short session to ensure the
# users row exists; db injects the per-handler session.
dp.message.outer_middleware(AuthMiddleware(session_factory=session_factory))
dp.callback_query.outer_middleware(AuthMiddleware(session_factory=session_factory))
dp.message.middleware(DbSessionMiddleware(session_factory))
dp.callback_query.middleware(DbSessionMiddleware(session_factory))

dp.include_router(folders_router)
dp.include_router(search_router)
dp.include_router(base_router)


async def _on_startup() -> None:
    from src.logging_setup import get_logger

    log = get_logger(__name__)
    log.info("bot.startup", bot_id=bot.id if bot.id else None)


async def _on_shutdown() -> None:
    from src.logging_setup import get_logger

    log = get_logger(__name__)
    log.info("bot.shutdown")


def run() -> None:
    import asyncio

    from src.logging_setup import get_logger, setup_logging

    setup_logging()
    log = get_logger(__name__)

    async def _main() -> None:
        await _on_startup()
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await _on_shutdown()
            await bot.session.close()

    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, SystemExit):
        log.info("bot.stopped_by_user")
