from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from openai import AsyncOpenAI

from src.config import settings
from src.logging_setup import get_logger

log = get_logger(__name__)


class EmbeddingsClient:
    """Async OpenAI embeddings client with batching and basic rate limiting."""

    def __init__(
        self,
        model: str | None = None,
        batch_size: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or settings.embedding_model
        self.batch_size = batch_size or settings.embedding_batch_size
        self.client = AsyncOpenAI(
            api_key=api_key or settings.openai_api_key,
            base_url=base_url or settings.openai_base_url,
        )

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i : i + self.batch_size])
            t0 = time.monotonic()
            try:
                resp = await self.client.embeddings.create(
                    input=batch, model=self.model
                )
            except Exception as exc:
                log.error("embeddings.error", error=str(exc), batch_size=len(batch))
                raise
            for item in resp.data:
                out.append(list(item.embedding))
            log.info(
                "embeddings.batch_done",
                count=len(batch),
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )
            # Light self-throttle to avoid bursts.
            await asyncio.sleep(0.05)
        return out

    async def embed_one(self, text: str) -> list[float]:
        res = await self.embed([text])
        return res[0]
