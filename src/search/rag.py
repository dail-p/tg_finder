from __future__ import annotations

from dataclasses import dataclass

from openai import AsyncOpenAI

from src.config import settings
from src.logging_setup import get_logger
from src.prompts.answer import SYSTEM_PROMPT, build_answer_prompt
from src.search.confidence import classify_confidence
from src.search.models import RetrievedChunk
from src.search.retrieval import Retriever

log = get_logger(__name__)


@dataclass
class SearchAnswer:
    text: str
    confidence: float
    level: str
    sources: list[RetrievedChunk]
    no_answer: bool


class RAGAnswerer:
    """Orchestrates retrieval -> LLM synthesis -> confidence classification."""

    def __init__(
        self,
        retriever: Retriever,
        llm: AsyncOpenAI | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm or AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    async def answer(
        self,
        session,
        question: str,
        channel_ids: list[int] | None = None,
    ) -> SearchAnswer:
        chunks = await self.retriever.search(session, question, channel_ids=channel_ids)

        if not chunks:
            return SearchAnswer(
                text=(
                    "К сожалению, в проиндексированных каналах нет информации "
                    "по вашему вопросу."
                ),
                confidence=0.0,
                level="low",
                sources=[],
                no_answer=True,
            )

        best_sim = chunks[0].similarity
        prompt = build_answer_prompt(question, chunks)

        try:
            completion = await self.llm.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            text = (completion.choices[0].message.content or "").strip()
        except Exception as exc:
            log.error("rag.llm_error", error=str(exc))
            # Fallback: return raw retrieved chunks with links.
            text = (
                "⚠️ Не удалось сформировать ответ через LLM. "
                "Вот наиболее релевантные посты-источники:\n\n"
                + "\n\n".join(
                    f"[{i}] {ch.to_link()}\n{ch.content[:300]}" for i, ch in enumerate(chunks, 1)
                )
            )

        no_answer = (
            "нет информации" in text.lower() and best_sim < settings.similarity_threshold
        )
        level = classify_confidence(best_sim)

        return SearchAnswer(
            text=text,
            confidence=round(best_sim, 3),
            level=level.value,
            sources=chunks,
            no_answer=no_answer,
        )

    async def answer_streaming(self, session, question: str, channel_ids=None):
        """Yield text chunks for streaming responses to Telegram."""
        chunks = await self.retriever.search(session, question, channel_ids=channel_ids)
        if not chunks:
            yield SearchAnswer(
                text=(
                    "К сожалению, в проиндексированных каналах нет информации "
                    "по вашему вопросу."
                ),
                confidence=0.0,
                level="low",
                sources=[],
                no_answer=True,
            )
            return

        prompt = build_answer_prompt(question, chunks)
        stream = await self.llm.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            stream=True,
        )

        collected: list[str] = []
        async for event in stream:
            delta = event.choices[0].delta if event.choices else None
            if delta and delta.content:
                collected.append(delta.content)

        best_sim = chunks[0].similarity
        full = "".join(collected).strip() or _fallback(chunks, question)
        yield SearchAnswer(
            text=full,
            confidence=round(best_sim, 3),
            level=classify_confidence(best_sim).value,
            sources=chunks,
            no_answer=False,
        )


def _fallback(chunks: list[RetrievedChunk], question: str) -> str:
    body = "\n\n".join(
        f"[{i}] {ch.to_link()}\n{ch.content[:300]}" for i, ch in enumerate(chunks, 1)
    )
    return (
        f"Не удалось сформировать ответ. По запросу «{question}» найдены источники:\n\n{body}"
    )
