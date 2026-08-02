from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Channel

base_router = Router(name="basic")

START_TEXT = (
    "👋 <b>Привет!</b>\n\n"
    "Я бот, который ищет информацию по постам Telegram-каналов с помощью "
    "семантического поиска (RAG).\n\n"
    "Доступные команды:\n"
    "/search <i>&lt;вопрос&gt;</i> — поиск по проиндексированным каналам\n"
    "/folders — ваши папки каналов (поиск по подмножеству каналов)\n"
    "/channels — список проиндексированных каналов\n"
    "/help — справка\n"
)

HELP_TEXT = (
    "<b>Справка</b>\n\n"
    "/search <i>&lt;ваш вопрос&gt;</i> — задать вопрос по содержимому каналов.\n"
    "Бот ответит сводным текстом и приложит ссылки на посты-источники.\n\n"
    "/folders — создать папки каналов и искать по конкретному набору каналов. "
    "Внутри папки можно добавлять каналы по @username или пересылкой поста.\n\n"
    "/channels — список каналов, по которым идёт поиск.\n\n"
    "<i>Если по теме нет данных, бот честно скажет об этом.</i>\n"
)


@base_router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT)


@base_router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@base_router.message(Command("channels"))
async def cmd_channels(message: Message, db_session: AsyncSession) -> None:
    result = await db_session.execute(select(Channel).order_by(Channel.title))
    channels = result.scalars().all()
    if not channels:
        await message.answer("Пока ни один канал не проиндексирован.")
        return
    lines = ["<b>Проиндексированные каналы:</b>\n"]
    for ch in channels:
        lines.append(f"• {ch.title} <code>{ch.telegram_id}</code>")
    await message.answer("\n".join(lines))


@base_router.message()
async def fallback(message: Message) -> None:
    await message.answer(
        "Используйте /search <i>&lt;вопрос&gt;</i> для поиска. "
        "Команды: /help"
    )
