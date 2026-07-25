from __future__ import annotations

from dataclasses import dataclass

import tiktoken
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Channel, Post
from src.logging_setup import get_logger
from src.prompts.answer import SYSTEM_PROMPT, build_answer_prompt
from src.search.llm import get_llm_client
from src.search.models import SelectedPost
from src.search.selector import TitleSelector

log = get_logger(__name__)

NO_ANSWER_TEXT = (
    "К сожалению, в проиндексированных каналах нет информации по вашему вопросу."
)


@dataclass
class SearchAnswer:
    text: str
    sources: list[SelectedPost]
    no_answer: bool


def _encoder_for(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def _post_token_cost(post: SelectedPost, model: str) -> int:
    enc = _encoder_for(model)
    text = f"{post.title}\n{post.content}\n{post.channel_title}"
    return len(enc.encode(text))


def fit_posts_to_budget(
    posts: list[SelectedPost],
    budget: int,
    model: str,
) -> list[SelectedPost]:
    if budget <= 0:
        return []
    kept: list[SelectedPost] = []
    used = 0
    for post in posts:
        cost = _post_token_cost(post, model)
        if kept and used + cost > budget:
            break
        if not kept and cost > budget:
            # Always include at least the first (most relevant) post.
            kept.append(post)
            break
        kept.append(post)
        used += cost
    return kept


class PostAnswerer:
    """Step 2 of the search pipeline: load selected posts and answer via LLM."""

    def __init__(
        self,
        selector: TitleSelector | None = None,
        llm: AsyncOpenAI | None = None,
    ) -> None:
        self.llm = llm or get_llm_client()
        self.selector = selector or TitleSelector(llm=self.llm)

    async def _load_posts(
        self,
        session: AsyncSession,
        ids: list[int],
    ) -> list[SelectedPost]:
        if not ids:
            return []
        stmt = (
            select(Post, Channel.title, Channel.telegram_id)
            .join(Channel, Channel.id == Post.channel_id)
            .where(Post.id.in_(ids))
        )
        rows = (await session.execute(stmt)).all()
        by_id: dict[int, SelectedPost] = {}
        for post, ch_title, ch_tg_id in rows:
            media = post.media if isinstance(post.media, list) else []
            hashtags = post.hashtags if isinstance(post.hashtags, list) else []
            by_id[post.id] = SelectedPost(
                post_id=post.id,
                title=post.title or "",
                content=post.content or "",
                hashtags=[str(t) for t in hashtags],
                media=[m for m in media if isinstance(m, dict)],
                channel_title=ch_title or "",
                channel_telegram_id=ch_tg_id or "",
                telegram_message_id=int(post.telegram_message_id),
                posted_at=post.posted_at,
                grouped_id=post.grouped_id,
            )
        # Preserve selector order (SQL does not).
        return [by_id[i] for i in ids if i in by_id]

    async def _attach_album_media(
        self,
        session: AsyncSession,
        posts: list[SelectedPost],
    ) -> None:
        group_ids = {p.grouped_id for p in posts if p.grouped_id is not None}
        if not group_ids:
            return

        selected_ids = {p.post_id for p in posts}
        stmt = select(Post.id, Post.grouped_id, Post.media).where(
            Post.grouped_id.in_(group_ids)
        )
        rows = (await session.execute(stmt)).all()

        by_group: dict[int, list[dict]] = {}
        for post_id, grouped_id, media in rows:
            if post_id in selected_ids:
                continue
            if grouped_id is None:
                continue
            items = media if isinstance(media, list) else []
            by_group.setdefault(int(grouped_id), []).extend(
                m for m in items if isinstance(m, dict)
            )

        for post in posts:
            if post.grouped_id is None:
                continue
            post.album_media = list(by_group.get(int(post.grouped_id), []))

    async def answer(
        self,
        session: AsyncSession,
        question: str,
        channel_ids: list[int] | None = None,
    ) -> SearchAnswer:
        ids = await self.selector.select(session, question, channel_ids=channel_ids)
        if not ids:
            return SearchAnswer(text=NO_ANSWER_TEXT, sources=[], no_answer=True)

        posts = await self._load_posts(session, ids)
        if not posts:
            return SearchAnswer(text=NO_ANSWER_TEXT, sources=[], no_answer=True)

        await self._attach_album_media(session, posts)

        model = settings.answer_model_name
        posts = fit_posts_to_budget(posts, settings.answer_token_budget, model)
        prompt = build_answer_prompt(question, posts)

        try:
            completion = await self.llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            text = (completion.choices[0].message.content or "").strip()
        except Exception as exc:
            log.error("answerer.llm_error", error=str(exc))
            text = (
                "⚠️ Не удалось сформировать ответ через LLM. "
                "Вот наиболее релевантные посты-источники:\n\n"
                + "\n\n".join(
                    f"[{i}] {p.to_link()}\n{(p.content or '')[:300]}"
                    for i, p in enumerate(posts, 1)
                )
            )
            return SearchAnswer(text=text, sources=posts, no_answer=False)

        first_line = text.splitlines()[0].strip() if text else ""
        if first_line == "NO_ANSWER":
            remainder = "\n".join(text.splitlines()[1:]).strip()
            return SearchAnswer(
                text=remainder or NO_ANSWER_TEXT,
                sources=posts,
                no_answer=True,
            )

        return SearchAnswer(text=text, sources=posts, no_answer=False)
