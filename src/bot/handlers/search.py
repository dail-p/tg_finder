from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_setup import get_logger
from src.search.answerer import PostAnswerer
from src.search.llm import get_llm_client
from src.search.selector import TitleSelector

search_router = Router(name="search")
log = get_logger(__name__)


def _format_answer(answer) -> str:
    if answer.no_answer or not answer.sources:
        return answer.text

    lines = [answer.text, ""]
    lines.append("<b>Источники:</b>")
    for i, src in enumerate(answer.sources, start=1):
        title = (src.title or "").strip()
        label = f"{src.channel_title} — {title}" if title else src.channel_title
        images = src.image_count()
        image_mark = f" 🖼 {images}" if images else ""
        lines.append(f'{i}. <a href="{src.to_link()}">{label}</a>{image_mark}')
    return "\n".join(lines)


@search_router.message(Command("search"))
async def cmd_search(
    message: Message, command: CommandObject, db_session: AsyncSession
) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Использование: <code>/search &lt;вопрос&gt;</code>\n"
            "Пример: <code>/search какие ингредиенты для солянки?</code>"
        )
        return

    await message.answer("🔍 Ищу по проиндексированным каналам…")

    llm = get_llm_client()
    answerer = PostAnswerer(selector=TitleSelector(llm=llm), llm=llm)

    try:
        answer = await answerer.answer(db_session, query)
    except Exception as exc:
        log.error("search.error", error=str(exc), query=query)
        await message.answer("⚠️ Произошла ошибка при поиске. Попробуйте позже.")
        return

    text = _format_answer(answer)
    # Telegram message limit is 4096 chars.
    if len(text) > 4000:
        text = text[:3990] + "…"
    await message.answer(text, disable_web_page_preview=True)
