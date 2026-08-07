from __future__ import annotations

from datetime import datetime

from src.prompts.answer import SYSTEM_PROMPT, build_answer_prompt
from src.search.models import SelectedPost


def _post(
    *,
    title: str = "Заголовок",
    content: str = "Тестовый контент поста.",
    channel: str = "@news",
    msg: int = 5,
    images: int = 0,
) -> SelectedPost:
    media = [{"kind": "photo"} for _ in range(images)]
    return SelectedPost(
        post_id=10,
        title=title,
        content=content,
        hashtags=["#ai"],
        media=media,
        channel_title="News",
        channel_telegram_id=channel,
        telegram_message_id=msg,
        posted_at=datetime(2026, 1, 2),
    )


def test_system_prompt_enforces_no_hallucination() -> None:
    assert "не выдумывай" in SYSTEM_PROMPT.lower()
    assert "no_answer" in SYSTEM_PROMPT.lower()


def test_prompt_includes_question_and_context() -> None:
    prompt = build_answer_prompt("что такое солянка?", [_post()])
    assert "что такое солянка?" in prompt
    assert "Тестовый контент поста." in prompt
    assert "News" in prompt
    assert "Заголовок" in prompt


def test_prompt_empty_context_mentions_empty() -> None:
    prompt = build_answer_prompt("вопрос", [])
    assert "пусто" in prompt.lower()
    assert "NO_ANSWER" in prompt


def test_prompt_contains_numbered_sources_and_image_count() -> None:
    prompt = build_answer_prompt("q", [_post(images=2), _post(msg=6, title="Второй")])
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "[изображений: 2]" in prompt


def test_context_has_no_raw_links_for_the_model_to_copy() -> None:
    prompt = build_answer_prompt("q", [_post()])
    assert "https://t.me/" not in prompt


def test_system_prompt_asks_for_inline_citations() -> None:
    assert "[N]" in SYSTEM_PROMPT or "[2]" in SYSTEM_PROMPT
    assert "не пиши url" in SYSTEM_PROMPT.lower()
