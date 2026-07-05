from __future__ import annotations

from src.bot.handlers.search import _format_answer
from src.search.models import RetrievedChunk
from src.search.rag import SearchAnswer


def _chunk(channel: str = "@news", msg: int = 42, sim: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        post_id=10,
        content="контекст",
        similarity=sim,
        channel_title="News",
        channel_telegram_id=channel,
        telegram_message_id=msg,
    )


def _answer(level: str, sim: float, no_answer: bool = False, sources=None, text="Ответ.") -> SearchAnswer:
    return SearchAnswer(
        text=text,
        confidence=sim,
        level=level,
        sources=sources if sources is not None else [],
        no_answer=no_answer,
    )


def test_no_answer_text_returned_as_is() -> None:
    ans = _answer("low", 0.0, no_answer=True, text="Нет информации.")
    out = _format_answer(ans)
    assert out == "Нет информации."


def test_includes_sources_as_html_links() -> None:
    ans = _answer("high", 0.9, sources=[_chunk("@news", 42)])
    out = _format_answer(ans)
    assert '<a href="https://t.me/news/42">News</a>' in out
    assert "Источники" in out


def test_high_confidence_label() -> None:
    ans = _answer("high", 0.9, sources=[_chunk()])
    assert "Высокая уверенность" in _format_answer(ans)


def test_medium_confidence_label() -> None:
    ans = _answer("medium", 0.5, sources=[_chunk()])
    assert "неполнота" in _format_answer(ans)


def test_low_confidence_label_with_sources() -> None:
    ans = _answer("low", 0.1, sources=[_chunk()])
    assert "Низкая уверенность" in _format_answer(ans)
