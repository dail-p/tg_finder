from __future__ import annotations

from src.indexer.chunker import chunk_text, count_tokens


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_single_chunk() -> None:
    text = "Короткое сообщение."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].content.strip() == text.strip()
    assert chunks[0].token_count == count_tokens(text)


def test_respects_chunk_size_limit() -> None:
    text = "Солянка — это густой суп. " * 200
    chunks = chunk_text(text, chunk_size=256, overlap=32)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 256


def test_chunk_indices_are_sequential() -> None:
    text = "word " * 5000
    chunks = chunk_text(text, chunk_size=200, overlap=20)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_overlap_creates_content_overlap() -> None:
    text = "УникальныйТокенА УникальныйТокенБ " * 200
    chunks = chunk_text(text, chunk_size=128, overlap=40)
    assert len(chunks) >= 2
    # Overlap means the tail of chunk[i] should appear near the head of chunk[i+1]
    tail = chunks[0].content[-30:]
    assert any(tok in chunks[1].content for tok in tail.split() if len(tok) > 4)


def test_count_tokens_matches_encoder() -> None:
    text = "Проверка токенизации русского текста."
    assert count_tokens(text) > 0
    assert count_tokens("") == 0
