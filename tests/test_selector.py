from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.search.selector import (
    TitleCandidate,
    TitleSelector,
    format_candidate_line,
    parse_selector_response,
    truncate_to_budget,
)


def _cand(
    post_id: int,
    title: str = "t",
    day: int = 1,
    channel: str = "News",
) -> TitleCandidate:
    return TitleCandidate(
        post_id=post_id,
        title=title,
        hashtags=["#ai"],
        channel_title=channel,
        posted_at=datetime(2026, 1, day),
    )


def test_format_candidate_line() -> None:
    line = format_candidate_line(_cand(12, title="Заголовок", day=5))
    assert line == "12 | News | 2026-01-05 | Заголовок | #ai"


def test_truncate_keeps_freshest_under_budget() -> None:
    # Freshest first: day 10, 9, 8...
    candidates = [_cand(i, title=f"title-{i}" * 20, day=i) for i in range(10, 0, -1)]
    kept, dropped = truncate_to_budget(candidates, budget=80, model="gpt-4o-mini")
    assert kept
    assert dropped >= 1
    # First kept must be the freshest (day 10 → id 10).
    assert kept[0].post_id == 10
    assert all(
        kept[i].posted_at >= kept[i + 1].posted_at  # type: ignore[operator]
        for i in range(len(kept) - 1)
    )


def test_truncate_zero_budget_drops_all() -> None:
    kept, dropped = truncate_to_budget([_cand(1)], budget=0, model="gpt-4o-mini")
    assert kept == []
    assert dropped == 1


def test_parse_selector_response_filters_and_limits() -> None:
    raw = '{"post_ids": [1, 99, 2, 1, "x", 3]}'
    out = parse_selector_response(raw, allowed={1, 2, 3}, max_selected=2)
    assert out == [1, 2]


def test_parse_selector_response_invalid_json() -> None:
    with pytest.raises(Exception):
        parse_selector_response("not-json", allowed={1}, max_selected=5)


@pytest.mark.asyncio
async def test_select_returns_empty_on_llm_error() -> None:
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
    selector = TitleSelector(llm=llm)

    session = AsyncMock()
    # One candidate row: id, title, hashtags, posted_at, channel_title
    session.execute = AsyncMock(
        return_value=SimpleNamespace(
            all=lambda: [
                (1, "Заголовок", ["#ai"], datetime(2026, 1, 1), "News"),
            ]
        )
    )

    out = await selector.select(session, "вопрос")
    assert out == []


@pytest.mark.asyncio
async def test_select_parses_valid_json() -> None:
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"post_ids": [1, 999, 2]}')
                )
            ]
        )
    )
    selector = TitleSelector(llm=llm)
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=SimpleNamespace(
            all=lambda: [
                (1, "A", [], datetime(2026, 1, 2), "News"),
                (2, "B", [], datetime(2026, 1, 1), "News"),
            ]
        )
    )

    out = await selector.select(session, "вопрос")
    assert out == [1, 2]
