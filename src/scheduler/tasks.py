from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.db.session import session_factory
from src.indexer.pipeline import index_all_channels
from src.indexer.retention import prune_old_posts
from src.logging_setup import get_logger
from src.parser.client import TelethonParser, get_telethon_client

log = get_logger(__name__)


async def _indexing_job() -> None:
    log.info("scheduler.indexing_job.start")
    client = get_telethon_client()
    try:
        await client.start()
        parser = TelethonParser(client)
        try:
            created = await index_all_channels(session_factory, parser)
            log.info("scheduler.indexing_job.done", new_posts=created)
        except Exception as exc:
            log.error("scheduler.indexing_job.error", error=str(exc))
    finally:
        await client.disconnect()


async def _retention_job() -> None:
    log.info("scheduler.retention_job.start", retention_days=settings.post_retention_days)
    try:
        async with session_factory() as s:
            deleted = await prune_old_posts(s)
        log.info("scheduler.retention_job.done", deleted=deleted)
    except Exception as exc:
        log.error("scheduler.retention_job.error", error=str(exc))


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _indexing_job,
        trigger=IntervalTrigger(minutes=settings.indexer_interval_minutes),
        id="index_all_channels",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if settings.retention_enabled:
        scheduler.add_job(
            _retention_job,
            trigger=IntervalTrigger(hours=settings.retention_interval_hours),
            id="prune_old_posts",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            # Interval jobs first fire one full interval after start; with a
            # daily interval a service that redeploys often would never prune.
            next_run_time=datetime.now(UTC),
        )
    return scheduler


async def run_scheduler() -> None:
    sched = build_scheduler()
    sched.start()
    log.info(
        "scheduler.started",
        interval_minutes=settings.indexer_interval_minutes,
        retention_days=settings.post_retention_days,
        retention_interval_hours=settings.retention_interval_hours,
    )
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        sched.shutdown(wait=False)
