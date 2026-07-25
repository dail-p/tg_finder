from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.search.answerer import (
    NO_ANSWER_TEXT,
    PostAnswerer,
    fit_posts_to_budget,
)
from src.search.models import SelectedPost


def _post(
    post_id: int,
    content: str = "body",
    title: str = "t",
    grouped_id: int | None = None,
    media: list | None = None,
) -> SelectedPost:
    return SelectedPost(
        post_id=post_id,
        title=title,
        content=content,
        hashtags=[],
        media=media or [],
        channel_title="News",
        channel_telegram_id="@news",
        telegram_message_id=post_id * 10,
        posted_at=datetime(2026, 1, 1),
        grouped_id=grouped_id,
    )


@pytest.mark.asyncio
async def test_empty_selection_is_no_answer() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[])
    answerer = PostAnswerer(selector=selector, llm=AsyncMock())

    ans = await answerer.answer(AsyncMock(), "вопрос")
    assert ans.no_answer is True
    assert ans.sources == []
    assert "нет информации" in ans.text.lower()


@pytest.mark.asyncio
async def test_post_order_follows_selector_ids() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[3, 1, 2])

    p1 = _db_post(1, "one")
    p2 = _db_post(2, "two")
    p3 = _db_post(3, "three")
    # SQL returns unordered
    session = _session_for_posts([p1, p3, p2])

    llm = _llm_mock("Ответ по постам.")
    answerer = PostAnswerer(selector=selector, llm=llm)
    ans = await answerer.answer(session, "вопрос")

    assert [s.post_id for s in ans.sources] == [3, 1, 2]
    assert ans.no_answer is False


@pytest.mark.asyncio
async def test_album_media_merged_from_neighbours() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[10])

    caption = _db_post(
        10,
        "подпись альбома",
        grouped_id=77,
        media=[{"kind": "photo", "order": 0}],
    )
    neighbour = SimpleNamespace(
        id=11,
        grouped_id=77,
        media=[{"kind": "photo", "order": 1}, {"kind": "photo", "order": 2}],
    )

    session = AsyncMock()
    # First execute: load selected posts; second: album neighbours.
    session.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(all=lambda: [(caption, "News", "@news")]),
            SimpleNamespace(
                all=lambda: [
                    (10, 77, caption.media),
                    (11, 77, neighbour.media),
                ]
            ),
        ]
    )

    answerer = PostAnswerer(selector=selector, llm=_llm_mock("ок"))
    ans = await answerer.answer(session, "вопрос")

    assert len(ans.sources) == 1
    assert ans.sources[0].image_count() == 3  # own + 2 neighbours
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_no_album_query_without_grouped_id() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[1])

    post = _db_post(1, "solo", grouped_id=None)
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(all=lambda: [(post, "News", "@news")])
    )

    answerer = PostAnswerer(selector=selector, llm=_llm_mock("ок"))
    await answerer.answer(session, "вопрос")
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_llm_error_fallback_lists_sources() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[1])
    post = _db_post(1, "контент")
    session = _session_for_posts([post])

    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(side_effect=RuntimeError("down"))
    answerer = PostAnswerer(selector=selector, llm=llm)
    ans = await answerer.answer(session, "вопрос")

    assert ans.no_answer is False
    assert "Не удалось сформировать ответ" in ans.text
    assert ans.sources


@pytest.mark.asyncio
async def test_no_answer_marker_recognized() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[1])
    session = _session_for_posts([_db_post(1, "x")])
    answerer = PostAnswerer(
        selector=selector, llm=_llm_mock("NO_ANSWER\nДанных нет.")
    )
    ans = await answerer.answer(session, "вопрос")
    assert ans.no_answer is True
    assert ans.text == "Данных нет."


@pytest.mark.asyncio
async def test_no_answer_marker_only_uses_default_text() -> None:
    selector = AsyncMock()
    selector.select = AsyncMock(return_value=[1])
    session = _session_for_posts([_db_post(1, "x")])
    answerer = PostAnswerer(selector=selector, llm=_llm_mock("NO_ANSWER"))
    ans = await answerer.answer(session, "вопрос")
    assert ans.no_answer is True
    assert ans.text == NO_ANSWER_TEXT


def test_fit_posts_to_budget_prefers_earlier() -> None:
    posts = [
        _post(1, content="short"),
        _post(2, content="word " * 500),
        _post(3, content="tail"),
    ]
    kept = fit_posts_to_budget(posts, budget=50, model="gpt-4o-mini")
    assert kept[0].post_id == 1
    assert all(p.post_id != 3 or len(kept) > 2 for p in kept)
    # Budget is small; at least the first post is kept.
    assert kept


def _db_post(
    post_id: int,
    content: str,
    *,
    grouped_id: int | None = None,
    media: list | None = None,
    title: str = "title",
):
    return SimpleNamespace(
        id=post_id,
        title=title,
        content=content,
        hashtags=[],
        media=media or [],
        telegram_message_id=post_id * 10,
        posted_at=datetime(2026, 1, 1),
        grouped_id=grouped_id,
    )


def _session_for_posts(posts: list) -> AsyncMock:
    session = AsyncMock()
    rows = [(p, "News", "@news") for p in posts]
    session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    return session


def _llm_mock(text: str) -> AsyncMock:
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
        )
    )
    return llm
