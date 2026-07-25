from __future__ import annotations

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
