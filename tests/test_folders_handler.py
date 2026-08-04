from __future__ import annotations

from types import SimpleNamespace

from src.bot.handlers.folders import (
    BACK_TO_LIST,
    NEW_PACK,
    _channel_cb,
    _channel_keyboard,
    _extract_channel_ref,
    _format_channel_card,
    _format_pack_card,
    _list_keyboard,
    _pack_cb,
    _pack_keyboard,
    _parse_channel_cb,
    _parse_pack_cb,
)
from src.db.models import Channel, ChannelPack


def _pack(name: str = "News", pack_id: int = 7) -> ChannelPack:
    return ChannelPack(id=pack_id, owner_id=111, name=name)


def test_parse_pack_cb_actions() -> None:
    assert _parse_pack_cb("fp:7:open") == (7, "open")
    assert _parse_pack_cb("fp:7:rename") == (7, "rename")
    assert _parse_pack_cb("fp:0:open") == (0, "open")


def test_parse_pack_cb_special() -> None:
    assert _parse_pack_cb(NEW_PACK) == (0, "new")
    assert _parse_pack_cb(BACK_TO_LIST) == (0, "list")


def test_parse_pack_cb_invalid() -> None:
    assert _parse_pack_cb("fr:7:5") is None
    assert _parse_pack_cb("fp:abc:open") is None
    assert _parse_pack_cb("xx") is None


def test_parse_channel_cb() -> None:
    assert _parse_channel_cb("fc:7:42:update") == (7, 42, "update")
    assert _parse_channel_cb("fp:7:open") is None
    assert _parse_channel_cb("fc:abc:42:update") is None


def test_pack_cb_format() -> None:
    assert _pack_cb(7, "open") == "fp:7:open"


def test_channel_cb_format() -> None:
    assert _channel_cb(7, 42, "open") == "fc:7:42:open"


def test_list_keyboard_includes_new_button() -> None:
    kb = _list_keyboard([_pack("A", 1), _pack("B", 2)])
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "fp:1:open" in callbacks
    assert "fp:2:open" in callbacks
    assert NEW_PACK in callbacks


def test_list_keyboard_empty() -> None:
    kb = _list_keyboard([])
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert flat == [NEW_PACK]


def test_pack_keyboard_buttons() -> None:
    kb = _pack_keyboard(7)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "fp:7:add" in flat
    assert "fp:7:search" in flat
    assert "fp:7:rename" in flat
    assert "fp:7:delete" in flat
    assert BACK_TO_LIST in flat


def test_pack_keyboard_has_channel_cards_and_management() -> None:
    channels = [
        Channel(id=10, telegram_id="@a", title="A"),
        Channel(id=20, telegram_id="@b", title="B"),
    ]
    kb = _pack_keyboard(7, channels)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "fc:7:10:open" in flat
    assert "fc:7:20:open" in flat
    assert "fp:7:add" in flat
    assert "fp:7:rename" in flat
    assert BACK_TO_LIST in flat


def test_channel_keyboard_has_update_remove_and_back() -> None:
    kb = _channel_keyboard(7, 10)
    flat = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "fc:7:10:update" in flat
    assert "fc:7:10:remove" in flat
    assert "fp:7:open" in flat


def test_format_pack_card_empty_channels() -> None:
    out = _format_pack_card(_pack("News", 7), [])
    assert "<b>News</b>" in out
    assert "В папке нет каналов." in out


def test_format_pack_card_with_channels_marks_unindexed() -> None:
    pack = _pack("News", 7)
    ch1 = Channel(id=10, telegram_id="@a", title="Alpha", last_indexed_message_id=100)
    ch2 = Channel(id=20, telegram_id="@b", title="Bravo", last_indexed_message_id=None)
    out = _format_pack_card(pack, [ch1, ch2])
    assert "Alpha" in out
    assert "Bravo ⏳" in out


def test_format_pack_card_escapes_name() -> None:
    out = _format_pack_card(_pack("<x>", 7), [])
    assert "<x>" not in out
    assert "&lt;x&gt;" in out


def test_format_channel_card_shows_index_status() -> None:
    channel = Channel(
        id=10,
        telegram_id="@news",
        title="News",
        last_indexed_message_id=42,
    )
    out = _format_channel_card(channel)
    assert "News" in out
    assert "@news" in out
    assert "42" in out


def _msg(text: str = "", forward_origin=None) -> SimpleNamespace:
    return SimpleNamespace(text=text, forward_origin=forward_origin)


def _origin_chat(username: str | None = None, chat_id: int | None = None) -> SimpleNamespace:
    chat = SimpleNamespace(username=username, id=chat_id)
    return SimpleNamespace(chat=chat, sender_chat=None)


def test_extract_channel_ref_from_username_text() -> None:
    tid, uname = _extract_channel_ref(_msg(text="@news"))
    assert tid == "@news"
    assert uname == "news"


def test_extract_channel_ref_from_bare_username() -> None:
    tid, uname = _extract_channel_ref(_msg(text="news"))
    assert tid == "@news"
    assert uname == "news"


def test_extract_channel_ref_from_tme_link() -> None:
    tid, uname = _extract_channel_ref(_msg(text="https://t.me/news"))
    assert tid == "@news"
    assert uname == "news"


def test_extract_channel_ref_from_forwarded_post_public() -> None:
    origin = _origin_chat(username="news")
    tid, uname = _extract_channel_ref(_msg(text="что угодно", forward_origin=origin))
    assert tid == "@news"
    assert uname == "news"


def test_extract_channel_ref_from_forwarded_post_private() -> None:
    origin = _origin_chat(username=None, chat_id=-1001234567890)
    tid, uname = _extract_channel_ref(_msg(text="что угодно", forward_origin=origin))
    assert tid == "-1001234567890"
    assert uname is None


def test_extract_channel_ref_garbage_returns_none() -> None:
    tid, uname = _extract_channel_ref(_msg(text="просто текст"))
    assert tid is None
    assert uname is None


def test_extract_channel_ref_post_link_is_not_channel() -> None:
    tid, uname = _extract_channel_ref(_msg(text="https://t.me/news/42"))
    assert tid is None
