"""Generate a Telethon StringSession for non-interactive (production) use.

Run this ONCE locally. It logs into your Telegram *user* account (the parser
uses a user session, not the bot token), performs the interactive code/2FA
prompt, and prints a session string.

Copy the printed value into the ``TELEGRAM_SESSION_STRING`` environment
variable in your deployment (e.g. Railway variables). Treat it as a secret:
it grants full access to the account.

Usage:
    python scripts/gen_session.py

Requires TELEGRAM_API_ID / TELEGRAM_API_HASH in the environment or .env.
"""

from __future__ import annotations

from telethon import TelegramClient
from telethon.sessions import StringSession

from src.config import settings


def main() -> None:
    api_id = settings.telegram_api_id
    api_hash = settings.telegram_api_hash

    if not api_id or not api_hash:
        raise SystemExit(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH must be set (env or .env)."
        )

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        session_string = client.session.save()
        print("\n=== TELEGRAM_SESSION_STRING (keep secret) ===\n")
        print(session_string)
        print("\nAdd this to your deployment environment variables.\n")


if __name__ == "__main__":
    main()
