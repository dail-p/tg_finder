from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.bot.handlers import search as search_handler
from src.bot.handlers.search import _format_answer
from src.search.answerer import SearchAnswer
from src.search.models import SelectedPost


def _post(
    channel: str = "@news",
    msg: int = 42,
    title: str = "Заголовок",
    images: int = 0,
) -> SelectedPost:
    media = [{"kind": "photo"} for _ in range(images)]
    return SelectedPost(
        post_id=10,
        title=title,
        content="контекст",
        hashtags=[],
        media=media,
        channel_title="News",
        channel_telegram_id=channel,
        telegram_message_id=msg,
        posted_at=None,
    )


def _answer(no_answer: bool = False, sources=None, text: str = "Ответ.") -> SearchAnswer:
    return SearchAnswer(
        text=text,
        sources=sources if sources is not None else [],
        no_answer=no_answer,
    )


def test_no_answer_text_returned_as_is() -> None:
    ans = _answer(no_answer=True, text="Нет информации.")
    out = _format_answer(ans)
    assert out == "Нет информации."


def test_includes_sources_as_html_links_with_title() -> None:
    ans = _answer(sources=[_post("@news", 42, title="Тема")])
    out = _format_answer(ans)
    assert '<a href="https://t.me/news/42">News — Тема</a>' in out
    assert "Источники" in out


def test_image_mark_on_sources() -> None:
    ans = _answer(sources=[_post(images=3)])
    out = _format_answer(ans)
    assert "🖼 3" in out


def test_no_confidence_block() -> None:
    ans = _answer(sources=[_post()])
    out = _format_answer(ans)
    assert "уверенность" not in out.lower()
    assert "similarity" not in out.lower()


def test_answer_text_with_html_special_chars_is_escaped() -> None:
    ans = _answer(text="Цена < 100 & больше 50 <b>жирный</b> текст")
    out = _format_answer(ans)
    assert "<b>жирный</b>" not in out
    assert "&lt;" in out
    assert "&amp;" in out


def test_source_title_with_html_special_chars_is_escaped() -> None:
    ans = _answer(sources=[_post(title="<script>alert(1)</script>")])
    out = _format_answer(ans)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_markdown_bold_and_headers_converted_to_html() -> None:
    ans = _answer(text="### Заголовок\n**жирный** обычный текст")
    out = _format_answer(ans)
    assert "<b>Заголовок</b>" in out
    assert "<b>жирный</b>" in out
    assert "###" not in out
    assert "**" not in out


def test_markdown_bullets_converted_to_dot() -> None:
    ans = _answer(text="- первый пункт\n- второй пункт")
    out = _format_answer(ans)
    assert "• первый пункт" in out
    assert "- первый" not in out


def test_markdown_horizontal_rule_removed() -> None:
    ans = _answer(text="текст\n---\nещё текст")
    out = _format_answer(ans)
    assert "---" not in out


def test_unclosed_markdown_token_left_as_plain_text() -> None:
    ans = _answer(text="начало **незакрытый жирный текст")
    out = _format_answer(ans)
    assert out.count("<b>") == out.count("</b>")


def test_long_answer_never_produces_dangling_tag() -> None:
    ans = _answer(
        text="слово " * 2000,
        sources=[_post(channel=f"@news{i}", msg=i) for i in range(50)],
    )
    out = _format_answer(ans)
    assert len(out) <= 4096
    assert out.count("<a ") == out.count("</a>")
    assert out.count("<b>") == out.count("</b>")


class _FakeMessage:
    def __init__(self, user_id: int = 111) -> None:
        self.from_user = SimpleNamespace(id=user_id)
        self.answers: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_search_requires_channels_in_users_folders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_channels(session, owner_id: int) -> list[int]:
        assert owner_id == 111
        return []

    monkeypatch.setattr(search_handler.packs, "get_user_channel_ids", no_channels)
    message = _FakeMessage()

    await search_handler.cmd_search(
        message,
        SimpleNamespace(args="что нового?"),
        object(),
    )

    assert len(message.answers) == 1
    assert "/folders" in message.answers[0][0]


@pytest.mark.asyncio
async def test_search_is_scoped_to_users_folder_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def user_channels(session, owner_id: int) -> list[int]:
        return [10, 20]

    class FakeAnswerer:
        def __init__(self, **kwargs) -> None:
            pass

        async def answer(self, session, question: str, channel_ids=None):
            captured["question"] = question
            captured["channel_ids"] = channel_ids
            return _answer(no_answer=True, text="Нет данных.")

    monkeypatch.setattr(search_handler.packs, "get_user_channel_ids", user_channels)
    monkeypatch.setattr(search_handler, "get_llm_client", lambda: object())
    monkeypatch.setattr(search_handler, "PostAnswerer", FakeAnswerer)
    message = _FakeMessage()

    await search_handler.cmd_search(
        message,
        SimpleNamespace(args="что нового?"),
        object(),
    )

    assert captured == {"question": "что нового?", "channel_ids": [10, 20]}
