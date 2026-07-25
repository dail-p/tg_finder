from __future__ import annotations

from datetime import datetime

from src.parser.models import ParsedPost
from src.search.models import SelectedPost


def _selected(channel: str, msg: int = 1, media: list | None = None) -> SelectedPost:
    return SelectedPost(
        post_id=2,
        title="t",
        content="c",
        hashtags=[],
        media=media or [],
        channel_title="t",
        channel_telegram_id=channel,
        telegram_message_id=msg,
        posted_at=None,
    )


def test_link_public_username() -> None:
    assert _selected("@news", 42).to_link() == "https://t.me/news/42"


def test_link_private_channel_minus100() -> None:
    assert _selected("-1001234567890", 7).to_link() == "https://t.me/c/1234567890/7"


def test_link_fallback_plain() -> None:
    assert _selected("1234567890", 3).to_link() == "https://t.me/1234567890/3"


def test_image_count_photos_only() -> None:
    post = _selected(
        "@x",
        media=[
            {"kind": "photo"},
            {"kind": "video"},
            {"kind": "photo"},
            {"kind": "document"},
        ],
    )
    assert post.image_count() == 2


def test_image_count_includes_album_media() -> None:
    post = _selected("@x", media=[{"kind": "photo"}])
    post.album_media = [{"kind": "photo"}, {"kind": "video"}]
    assert post.image_count() == 2


def test_parsed_post_is_text_true_when_content() -> None:
    p = ParsedPost(
        telegram_message_id=1, content="привет", media_type="text", posted_at=None
    )
    assert p.is_text is True


def test_parsed_post_is_text_false_when_empty() -> None:
    p = ParsedPost(
        telegram_message_id=1, content="", media_type="photo", posted_at=None
    )
    assert p.is_text is False


def test_parsed_post_is_text_false_when_whitespace() -> None:
    p = ParsedPost(
        telegram_message_id=1,
        content="   ",
        media_type="video",
        posted_at=datetime.utcnow(),
    )
    assert p.is_text is False
