from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Channel, Post, PostChunk
from src.indexer.embeddings import EmbeddingsClient
from src.search.models import RetrievedChunk

DISTANCE_LABEL = "distance"


@dataclass
class _Row:
    distance: float
    chunk: PostChunk
    channel_title: str
    channel_telegram_id: str
    telegram_message_id: int


class Retriever:
    """pgvector ANN cosine-similarity retrieval."""

    def __init__(self, embeddings: EmbeddingsClient, top_k: int | None = None) -> None:
        self.embeddings = embeddings
        self.top_k = top_k or settings.search_top_k

    async def search(
        self,
        session: AsyncSession,
        query: str,
        channel_ids: list[int] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        k = top_k or self.top_k
        if not query.strip():
            return []

        qvec = await self.embeddings.embed_one(query)

        distance = PostChunk.embedding.cosine_distance(qvec).label(DISTANCE_LABEL)
        stmt = (
            select(
                PostChunk,
                Channel.title,
                Channel.telegram_id,
                Post.telegram_message_id,
                distance,
            )
            .join(Post, Post.id == PostChunk.post_id)
            .join(Channel, Channel.id == Post.channel_id)
            .where(PostChunk.embedding.isnot(None))
            .order_by(DISTANCE_LABEL)
            .limit(k * 2)  # over-fetch to dedup by post below
        )
        if channel_ids:
            stmt = stmt.where(Post.channel_id.in_(channel_ids))

        rows = (await session.execute(stmt)).all()

        seen_posts: set[int] = set()
        out: list[RetrievedChunk] = []
        for chunk, ch_title, ch_telegram_id, msg_id, dist in rows:
            if chunk.post_id in seen_posts:
                continue
            seen_posts.add(chunk.post_id)
            sim = max(0.0, 1.0 - float(dist))
            out.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    post_id=chunk.post_id,
                    content=chunk.content,
                    similarity=sim,
                    channel_title=ch_title,
                    channel_telegram_id=ch_telegram_id,
                    telegram_message_id=int(msg_id),
                )
            )
            if len(out) >= k:
                break
        return out
