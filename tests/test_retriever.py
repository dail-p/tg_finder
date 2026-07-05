from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.search.retrieval import Retriever
from tests.conftest import FakeEmbeddings, make_unit_vector


@dataclass
class FakeChunk:
    id: int
    post_id: int
    content: str


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class FakeSession:
    """Records executed statements and returns canned rows."""

    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows or []
        self.executed: list = []

    async def execute(self, stmt) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self.rows)


def _row(chunk_id: int, post_id: int, dist: float, title="News", tg_id="@news", msg=5):
    return (FakeChunk(id=chunk_id, post_id=post_id, content="контент"), title, tg_id, msg, dist)


@pytest.mark.asyncio
async def test_empty_query_returns_empty() -> None:
    emb = FakeEmbeddings()
    retriever = Retriever(emb, top_k=5)
    session = FakeSession(rows=[_row(1, 1, 0.1)])
    assert await retriever.search(session, "   ") == []
    assert session.executed == []  # short-circuit before DB


@pytest.mark.asyncio
async def test_dedups_by_post_id() -> None:
    emb = FakeEmbeddings()
    retriever = Retriever(emb, top_k=10)
    # Two chunks belonging to the same post -> only first kept.
    rows = [_row(1, 100, 0.05), _row(2, 100, 0.10), _row(3, 200, 0.20)]
    session = FakeSession(rows=rows)
    results = await retriever.search(session, "вопрос")
    assert len(results) == 2
    assert results[0].post_id == 100
    assert results[1].post_id == 200


@pytest.mark.asyncio
async def test_similarity_is_one_minus_distance() -> None:
    emb = FakeEmbeddings()
    retriever = Retriever(emb, top_k=5)
    session = FakeSession(rows=[_row(1, 1, 0.25)])
    results = await retriever.search(session, "q")
    assert results[0].similarity == pytest.approx(0.75, rel=1e-6)


@pytest.mark.asyncio
async def test_clamps_negative_similarity_to_zero() -> None:
    emb = FakeEmbeddings()
    retriever = Retriever(emb, top_k=5)
    session = FakeSession(rows=[_row(1, 1, 1.5)])  # distance > 1
    results = await retriever.search(session, "q")
    assert results[0].similarity == 0.0


@pytest.mark.asyncio
async def test_respects_top_k_limit() -> None:
    emb = FakeEmbeddings()
    retriever = Retriever(emb, top_k=2)
    rows = [_row(i, i, 0.01 * i) for i in range(1, 6)]
    session = FakeSession(rows=rows)
    results = await retriever.search(session, "q")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_uses_query_embedding(fake_embeddings: FakeEmbeddings) -> None:
    qvec = make_unit_vector(seed=99)
    fake_embeddings.register("вопрос", qvec)
    retriever = Retriever(fake_embeddings, top_k=1)
    session = FakeSession(rows=[_row(1, 1, 0.0)])
    await retriever.search(session, "вопрос")
    assert fake_embeddings.calls[-1] == ["вопрос"]
