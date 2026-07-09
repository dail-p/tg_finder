from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from src.parser.models import ParsedPost, _to_naive_utc


def test_to_naive_utc_none() -> None:
    assert _to_naive_utc(None) is None


def test_to_naive_utc_naive_passthrough() -> None:
    dt = datetime(2026, 7, 8, 5, 17, 56)
    result = _to_naive_utc(dt)
    assert result == dt
    assert result.tzinfo is None


def test_to_naive_utc_utc_aware_strips_tzinfo() -> None:
    # The exact shape from the reported error: aware UTC datetime.
    aware = datetime(2026, 7, 8, 5, 17, 56, tzinfo=UTC)
    result = _to_naive_utc(aware)
    assert result == datetime(2026, 7, 8, 5, 17, 56)
    assert result.tzinfo is None


def test_to_naive_utc_non_utc_offset_converts_to_utc() -> None:
    # 12:00 in UTC+3 -> 09:00 UTC, tzinfo removed.
    aware = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    result = _to_naive_utc(aware)
    assert result == datetime(2026, 7, 8, 9, 0, 0)
    assert result.tzinfo is None


def test_parsed_post_normalizes_aware_posted_at() -> None:
    aware = datetime(2026, 7, 8, 5, 17, 56, tzinfo=UTC)
    post = ParsedPost(
        telegram_message_id=1,
        content="text",
        media_type="text",
        posted_at=aware,
    )
    assert post.posted_at is not None
    assert post.posted_at.tzinfo is None
    assert post.posted_at == datetime(2026, 7, 8, 5, 17, 56)


def test_parsed_post_normalizes_non_utc_offset_posted_at() -> None:
    aware = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    post = ParsedPost(
        telegram_message_id=1,
        content="text",
        media_type="text",
        posted_at=aware,
    )
    assert post.posted_at == datetime(2026, 7, 8, 9, 0, 0)
    assert post.posted_at.tzinfo is None


def test_parsed_post_preserves_naive_posted_at() -> None:
    naive = datetime(2026, 7, 8, 5, 17, 56)
    post = ParsedPost(
        telegram_message_id=1,
        content="text",
        media_type="text",
        posted_at=naive,
    )
    assert post.posted_at == naive
    assert post.posted_at.tzinfo is None


def test_parsed_post_accepts_none_posted_at() -> None:
    post = ParsedPost(
        telegram_message_id=1,
        content="text",
        media_type="text",
        posted_at=None,
    )
    assert post.posted_at is None
