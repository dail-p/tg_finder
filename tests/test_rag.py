from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.search.models import RetrievedChunk
from src.search.rag import RAGAnswerer


def _chunk(sim: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1,
        post_id=10,
        content="Контекст поста.",
        similarity=sim,
        channel_title="News",
        channel_telegram_id="@news",
        telegram_message_id=42,
    )


class _StubRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.calls: list[str] = []

    async def search(self, session, query, channel_ids=None, top_k=None):
        self.calls.append(query)
        return self._chunks


def _llm_mock(content: str) -> AsyncMock:
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(return_value=completion)
    return llm


@pytest.mark.asyncio
async def test_no_chunks_returns_no_answer() -> None:
    answerer = RAGAnswerer(retriever=_StubRetriever([]), llm=_llm_mock("ignored"))
    answer = await answerer.answer(session=None, question="q")
    assert answer.no_answer is True
    assert answer.sources == []
    assert answer.confidence == 0.0
    assert answer.level == "low"
    assert "нет информации" in answer.text.lower()


@pytest.mark.asyncio
async def test_high_confidence_answer() -> None:
    answerer = RAGAnswerer(
        retriever=_StubRetriever([_chunk(0.9)]),
        llm=_llm_mock("Солянка — суп. [1](https://t.me/news/42)"),
    )
    answer = await answerer.answer(session=None, question="что такое солянка?")
    assert answer.no_answer is False
    assert answer.level == "high"
    assert answer.confidence == pytest.approx(0.9, rel=1e-6)
    assert "Солянка" in answer.text
    assert len(answer.sources) == 1


@pytest.mark.asyncio
async def test_medium_confidence_when_sim_in_range() -> None:
    answerer = RAGAnswerer(
        retriever=_StubRetriever([_chunk(0.55)]),
        llm=_llm_mock("частичный ответ"),
    )
    answer = await answerer.answer(session=None, question="q")
    assert answer.level == "medium"
    assert answer.no_answer is False


@pytest.mark.asyncio
async def test_low_confidence_level_kept() -> None:
    answerer = RAGAnswerer(
        retriever=_StubRetriever([_chunk(0.1)]),
        llm=_llm_mock("что-то"),
    )
    answer = await answerer.answer(session=None, question="q")
    assert answer.level == "low"


@pytest.mark.asyncio
async def test_no_answer_when_low_sim_and_text_says_no_info() -> None:
    answerer = RAGAnswerer(
        retriever=_StubRetriever([_chunk(0.1)]),
        llm=_llm_mock("К сожалению, нет информации по вашему вопросу."),
    )
    answer = await answerer.answer(session=None, question="q")
    assert answer.no_answer is True


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_chunks() -> None:
    llm = AsyncMock()
    llm.chat.completions.create = AsyncMock(side_effect=RuntimeError("openai down"))
    answerer = RAGAnswerer(
        retriever=_StubRetriever([_chunk(0.8)]),
        llm=llm,
    )
    answer = await answerer.answer(session=None, question="q")
    assert answer.no_answer is False
    assert "https://t.me/news/42" in answer.text
    assert answer.confidence == pytest.approx(0.8, rel=1e-6)


@pytest.mark.asyncio
async def test_retriever_query_forwarded(fake_embeddings) -> None:
    retriever = _StubRetriever([_chunk(0.9)])
    answerer = RAGAnswerer(retriever=retriever, llm=_llm_mock("ok"))
    await answerer.answer(session=None, question="рецепт солянки")
    assert retriever.calls == ["рецепт солянки"]
