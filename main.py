from __future__ import annotations

import asyncio
import os


def main() -> None:
    """Run the bot together with the periodic indexing scheduler."""
    from src.bot.app import bot, dp
    from src.config import settings
    from src.db.session import init_db
    from src.logging_setup import get_logger, setup_logging
    from src.scheduler.tasks import build_scheduler

    setup_logging()
    log = get_logger(__name__)

    mode = os.environ.get("APP_MODE", "bot")

    async def _bot_only() -> None:
        await init_db()
        log.info("main.bot_only.start")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            await bot.session.close()

    async def _bot_and_scheduler() -> None:
        await init_db()
        scheduler = build_scheduler()
        scheduler.start()
        log.info(
            "main.bot_and_scheduler.start",
            indexer_interval_minutes=settings.indexer_interval_minutes,
        )
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            scheduler.shutdown(wait=False)
            await bot.session.close()

    try:
        if mode == "scheduler":
            from src.scheduler.tasks import run_scheduler

            asyncio.run(run_scheduler())
        elif mode == "bot":
            asyncio.run(_bot_only())
        else:  # default: run both
            asyncio.run(_bot_and_scheduler())
    except (KeyboardInterrupt, SystemExit):
        log.info("main.stopped_by_user")


if __name__ == "__main__":
    main()
