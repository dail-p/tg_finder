from __future__ import annotations

from src.prompts.answer import SYSTEM_PROMPT, build_answer_prompt
from src.search.models import RetrievedChunk


def _chunk(sim: float = 0.9, channel: str = "@news", msg: int = 5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        post_id=10,
        content="Тестовый контент поста.",
        similarity=sim,
        channel_title="News",
        channel_telegram_id=channel,
        telegram_message_id=msg,
    )


def test_system_prompt_enforces_no_hallucination() -> None:
    assert "не выдумывай" in SYSTEM_PROMPT.lower()
    assert "контекст" in SYSTEM_PROMPT.lower()


def test_prompt_includes_question_and_context() -> None:
    prompt = build_answer_prompt("что такое солянка?", [_chunk()])
    assert "что такое солянка?" in prompt
    assert "Тестовый контент поста." in prompt
    assert "News" in prompt


def test_prompt_empty_context_mentions_empty() -> None:
    prompt = build_answer_prompt("вопрос", [])
    assert "пусто" in prompt.lower()


def test_prompt_contains_numbered_sources() -> None:
    prompt = build_answer_prompt("q", [_chunk(), _chunk(msg=6)])
    assert "[1]" in prompt
    assert "[2]" in prompt
