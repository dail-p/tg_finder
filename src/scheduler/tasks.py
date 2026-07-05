from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.db.session import session_factory
from src.indexer.embeddings import EmbeddingsClient
from src.indexer.pipeline import index_all_channels
from src.logging_setup import get_logger
from src.parser.client import TelethonParser, get_telethon_client

log = get_logger(__name__)


async def _indexing_job() -> None:
    log.info("scheduler.indexing_job.start")
    client = get_telethon_client()
    try:
        await client.start()
        parser = TelethonParser(client)
        embeddings = EmbeddingsClient()
        try:
            created = await index_all_channels(session_factory, parser, embeddings)
            log.info("scheduler.indexing_job.done", new_posts=created)
        except Exception as exc:
            log.error("scheduler.indexing_job.error", error=str(exc))
    finally:
        await client.disconnect()


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
    return scheduler


async def run_scheduler() -> None:
    sched = build_scheduler()
    sched.start()
    log.info("scheduler.started", interval_minutes=settings.indexer_interval_minutes)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        sched.shutdown(wait=False)
