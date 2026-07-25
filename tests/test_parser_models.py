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
    aware = datetime(2026, 7, 8, 5, 17, 56, tzinfo=UTC)
    result = _to_naive_utc(aware)
    assert result == datetime(2026, 7, 8, 5, 17, 56)
    assert result.tzinfo is None


def test_to_naive_utc_non_utc_offset_converts_to_utc() -> None:
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


def test_parsed_post_derives_title_and_hashtags() -> None:
    post = ParsedPost(
        telegram_message_id=1,
        content="Первый абзац\n\nОстальное #AI #News",
        media_type="text",
        posted_at=None,
    )
    assert post.title == "Первый абзац"
    assert post.hashtags == ["#ai", "#news"]
    assert post.media == []
    assert post.grouped_id is None


def test_parsed_post_keeps_explicit_title_hashtags_media() -> None:
    media = [{"kind": "photo", "order": 0}]
    post = ParsedPost(
        telegram_message_id=1,
        content="Игнор #x",
        media_type="photo",
        posted_at=None,
        title="Явный",
        hashtags=["#keep"],
        media=media,
        grouped_id=55,
    )
    assert post.title == "Явный"
    assert post.hashtags == ["#keep"]
    assert post.media == media
    assert post.grouped_id == 55
