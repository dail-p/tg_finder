from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import tiktoken
from openai import AsyncOpenAI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Channel, Post
from src.logging_setup import get_logger
from src.prompts.select import SYSTEM_PROMPT, build_select_prompt
from src.search.llm import get_llm_client

log = get_logger(__name__)


@dataclass
class TitleCandidate:
    post_id: int
    title: str
    hashtags: list[str]
    channel_title: str
    posted_at: datetime | None


def _encoder_for(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def format_candidate_line(c: TitleCandidate) -> str:
    date = c.posted_at.strftime("%Y-%m-%d") if c.posted_at else "—"
    tags = " ".join(c.hashtags) if c.hashtags else ""
    return f"{c.post_id} | {c.channel_title} | {date} | {c.title} | {tags}".rstrip()


def truncate_to_budget(
    candidates: list[TitleCandidate],
    budget: int,
    model: str,
) -> tuple[list[TitleCandidate], int]:
    """Keep freshest candidates that fit into the token budget.

    ``candidates`` must already be ordered by posted_at DESC (freshest first).
    Returns (kept, dropped_count).
    """
    if budget <= 0:
        return [], len(candidates)

    enc = _encoder_for(model)
    kept: list[TitleCandidate] = []
    used = 0
    for c in candidates:
        line = format_candidate_line(c)
        cost = len(enc.encode(line))
        if used + cost > budget:
            break
        kept.append(c)
        used += cost
    dropped = len(candidates) - len(kept)
    return kept, dropped


def parse_selector_response(raw: str, allowed: set[int], max_selected: int) -> list[int]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("selector response is not an object")
    ids = data.get("post_ids", [])
    if not isinstance(ids, list):
        raise ValueError("post_ids is not a list")
    out: list[int] = []
    seen: set[int] = set()
    for item in ids:
        try:
            pid = int(item)
        except (TypeError, ValueError):
            continue
        if pid not in allowed or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
        if len(out) >= max_selected:
            break
    return out


class TitleSelector:
    """Step 1 of the search pipeline: pick relevant posts by titles alone."""

    def __init__(self, llm: AsyncOpenAI | None = None) -> None:
        self.llm = llm or get_llm_client()

    async def _load_candidates(
        self,
        session: AsyncSession,
        channel_ids: list[int] | None,
    ) -> list[TitleCandidate]:
        stmt = (
            select(
                Post.id,
                Post.title,
                Post.hashtags,
                Post.posted_at,
                Channel.title,
            )
            .join(Channel, Channel.id == Post.channel_id)
            .where(Post.title != "")
            .order_by(text("posts.posted_at DESC NULLS LAST"))
            .limit(settings.selector_max_posts)
        )
        if channel_ids:
            stmt = stmt.where(Post.channel_id.in_(channel_ids))

        rows = (await session.execute(stmt)).all()
        out: list[TitleCandidate] = []
        for post_id, title, hashtags, posted_at, channel_title in rows:
            tags = hashtags if isinstance(hashtags, list) else []
            out.append(
                TitleCandidate(
                    post_id=int(post_id),
                    title=title or "",
                    hashtags=[str(t) for t in tags],
                    channel_title=channel_title or "",
                    posted_at=posted_at,
                )
            )
        return out

    async def select(
        self,
        session: AsyncSession,
        question: str,
        channel_ids: list[int] | None = None,
    ) -> list[int]:
        if not question.strip():
            return []

        candidates = await self._load_candidates(session, channel_ids)
        if not candidates:
            return []

        model = settings.selector_model_name
        kept, dropped = truncate_to_budget(
            candidates,
            settings.selector_token_budget,
            model,
        )
        if dropped:
            log.info(
                "selector.truncated",
                dropped=dropped,
                kept=len(kept),
                budget=settings.selector_token_budget,
            )
        if not kept:
            return []

        lines = [format_candidate_line(c) for c in kept]
        allowed = {c.post_id for c in kept}
        prompt = build_select_prompt(question, lines)

        try:
            completion = await self.llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw = (completion.choices[0].message.content or "").strip()
            return parse_selector_response(
                raw, allowed, settings.selector_max_selected
            )
        except Exception as exc:
            log.error("selector.llm_error", error=str(exc))
            return []
