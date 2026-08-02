from __future__ import annotations

import re
from html import escape as html_escape

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

# Telegram's hard message cap is 4096 chars; keep slack for HTML-escaping growth
# (e.g. a raw "&" becomes "&amp;") so the final, escaped message never overflows.
TELEGRAM_MESSAGE_LIMIT = 4096
BODY_CHAR_BUDGET = 3500
SOURCES_CHAR_BUDGET = TELEGRAM_MESSAGE_LIMIT - 50


# LLMs default to Markdown-ish formatting; Telegram's HTML parse_mode doesn't
# understand it, so it shows up as literal "**"/"###" clutter. Convert the
# common tokens to HTML tags. Substitutions only fire on complete open+close
# pairs, so a token truncation cuts in half is left as harmless plain text
# rather than an unclosed tag that would break the whole message.
_HR_RE = re.compile(r"^ {0,3}([-*_])( ?\1){2,}[ \t]*$", re.MULTILINE)
_HEADER_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_CODE_RE = re.compile(r"`([^`\n]+)`")
_BULLET_RE = re.compile(r"^[ \t]*[-*][ \t]+", re.MULTILINE)


def _markdown_to_html(text: str) -> str:
    text = html_escape(text)
    text = _HR_RE.sub("", text)
    text = _HEADER_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _BULLET_RE.sub("• ", text)
    return text


def _truncate_plain(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("\n\n", "\n", " "):
        pos = cut.rfind(sep)
        if pos > limit // 2:
            cut = cut[:pos]
            break
    return cut.rstrip() + "…"


def _format_source_line(i: int, src) -> str:
    title = (src.title or "").strip()
    label = f"{src.channel_title} — {title}" if title else src.channel_title
    images = src.image_count()
    image_mark = f" 🖼 {images}" if images else ""
    href = html_escape(src.to_link(), quote=True)
    return f'{i}. <a href="{href}">{html_escape(label)}</a>{image_mark}'


def format_answer_for_message(answer) -> str:
    # answer.text comes from the LLM and titles/channel names come from raw
    # Telegram post content — neither is safe HTML, so escape before embedding.
    body = _markdown_to_html(_truncate_plain(answer.text, BODY_CHAR_BUDGET))
    if answer.no_answer or not answer.sources:
        return body

    lines = [body, "", "<b>Источники:</b>"]
    used = len("\n".join(lines))
    for i, src in enumerate(answer.sources, start=1):
        line = _format_source_line(i, src)
        if used + len(line) + 1 > SOURCES_CHAR_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


# Back-compat alias used by tests.
def _format_answer(answer) -> str:
    return format_answer_for_message(answer)


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
    await message.answer(text, disable_web_page_preview=True)
