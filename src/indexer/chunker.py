from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from src.config import settings


def _get_encoder() -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(settings.embedding_model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


_ENCODER = _get_encoder()


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int


def count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text))


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[Chunk]:
    """Split text into overlapping token-bounded chunks.

    Uses a sliding-window approach over tokens to honour semantic continuity
    while keeping each chunk within embedding model context limits.
    """
    if not text or not text.strip():
        return []

    chunk_size = chunk_size or settings.chunk_size_tokens
    overlap = overlap or settings.chunk_overlap_tokens
    if overlap >= chunk_size:
        overlap = chunk_size // 4

    tokens = _ENCODER.encode(text)
    if not tokens:
        return []

    chunks: list[Chunk] = []
    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size

    idx = 0
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        piece = _ENCODER.decode(tokens[start:end])
        piece = piece.strip()
        if piece:
            chunks.append(Chunk(index=idx, content=piece, token_count=end - start))
            idx += 1
        if end >= len(tokens):
            break
        start += step

    return chunks
