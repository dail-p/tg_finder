from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from src.db.session import session_factory
from src.indexer.pipeline import index_channel
from src.logging_setup import get_logger, setup_logging
from src.parser.client import TelethonParser, get_telethon_client

log = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tg-finder-index",
        description="Manually add and index a Telegram channel",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="Add a channel by @username or chat id and index it")
    add.add_argument("channel", help="Channel @username or numeric id (e.g. @news or -100123)")
    add.add_argument(
        "--full",
        action="store_true",
        help="Re-index from scratch (ignore last_indexed_message_id)",
    )
    add.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Fetch only the N most recent posts (default: PARSER_HISTORY_LIMIT)",
    )

    sub.add_parser("list", help="List indexed channels")

    prune = sub.add_parser("prune", help="Delete posts older than the retention window")
    prune.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help="Retention window in days (default: POST_RETENTION_DAYS)",
    )
    prune.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many posts would be deleted",
    )

    return p


async def _add_channel(channel: str, full: bool, limit: int | None = None) -> None:
    client = get_telethon_client()
    await client.start()
    try:
        parser = TelethonParser(client)
        async with session_factory() as s:
            ch, created = await index_channel(
                s, parser, channel, incremental=not full, limit=limit
            )
        log.info("cli.add.done", channel=ch.title, created=created, limit=limit)
        print(f"✓ Indexed channel {ch.title!r} ({ch.telegram_id}); new posts: {created}")
    finally:
        await client.disconnect()


async def _list_channels() -> None:
    from sqlalchemy import select

    from src.db.models import Channel

    async with session_factory() as s:
        result = await s.execute(select(Channel).order_by(Channel.title))
        rows = result.scalars().all()
    if not rows:
        print("No channels indexed.")
        return
    for ch in rows:
        print(
            f"- {ch.title} | id={ch.telegram_id} | username={ch.username} "
            f"| last_msg={ch.last_indexed_message_id}"
        )


async def _prune_posts(days: int | None, dry_run: bool) -> None:
    from src.config import settings
    from src.indexer.retention import count_old_posts, prune_old_posts

    window = settings.post_retention_days if days is None else days
    if window <= 0:
        print("Retention is disabled (POST_RETENTION_DAYS <= 0); nothing to prune.")
        return

    async with session_factory() as s:
        if dry_run:
            n = await count_old_posts(s, days)
            print(f"Would delete {n} post(s) older than {window} day(s).")
            return
        deleted = await prune_old_posts(s, days)
    log.info("cli.prune.done", deleted=deleted, retention_days=window)
    print(f"✓ Deleted {deleted} post(s) older than {window} day(s).")


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = _build_parser().parse_args(argv)

    if args.cmd == "add":
        if args.limit is not None and args.limit < 1:
            print("--limit must be a positive integer", file=sys.stderr)
            return 2
        asyncio.run(_add_channel(args.channel, args.full, args.limit))
    elif args.cmd == "list":
        asyncio.run(_list_channels())
    elif args.cmd == "prune":
        asyncio.run(_prune_posts(args.days, args.dry_run))
    else:  # pragma: no cover
        print(f"Unknown command: {args.cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
