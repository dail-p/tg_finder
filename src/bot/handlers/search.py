from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.indexer.embeddings import EmbeddingsClient
from src.logging_setup import get_logger
from src.search.rag import RAGAnswerer
from src.search.retrieval import Retriever

search_router = Router(name="search")
log = get_logger(__name__)


def _format_answer(answer) -> str:
    if answer.no_answer or not answer.sources:
        return answer.text

    lines = [answer.text, ""]
    lines.append("<b>Источники:</b>")
    for i, src in enumerate(answer.sources, start=1):
        lines.append(f'{i}. <a href="{src.to_link()}">{src.channel_title}</a>')
    confidence_note = {
        "high": "✅ Высокая уверенность",
        "medium": "⚠️ Возможна неполнота ответа",
        "low": "❓ Низкая уверенность",
    }.get(answer.level, "")
    lines.append(f"\n<i>{confidence_note} (similarity={answer.confidence})</i>")
    return "\n".join(lines)


@search_router.message(Command("search"))
async def cmd_search(message: Message, command: CommandObject, db_session: AsyncSession) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.answer(
            "Использование: <code>/search &lt;вопрос&gt;</code>\n"
            "Пример: <code>/search какие ингредиенты для солянки?</code>"
        )
        return

    await message.answer("🔍 Ищу по проиндексированным каналам…")

    embeddings = EmbeddingsClient()
    retriever = Retriever(embeddings)
    answerer = RAGAnswerer(retriever)

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
