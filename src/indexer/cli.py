from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from src.config import settings
from src.db.session import session_factory
from src.indexer.embeddings import EmbeddingsClient
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

    sub.add_parser("list", help="List indexed channels")

    return p


async def _add_channel(channel: str, full: bool) -> None:
    client = get_telethon_client()
    await client.start(phone=None if not settings.telegram_session_string else None)
    try:
        parser = TelethonParser(client)
        embeddings = EmbeddingsClient()
        async with session_factory() as s:
            ch, created = await index_channel(
                s, parser, embeddings, channel, incremental=not full
            )
        log.info("cli.add.done", channel=ch.title, created=created)
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
        print(f"- {ch.title} | id={ch.telegram_id} | username={ch.username} | last_msg={ch.last_indexed_message_id}")


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = _build_parser().parse_args(argv)

    if args.cmd == "add":
        asyncio.run(_add_channel(args.channel, args.full))
    elif args.cmd == "list":
        asyncio.run(_list_channels())
    else:  # pragma: no cover
        print(f"Unknown command: {args.cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
