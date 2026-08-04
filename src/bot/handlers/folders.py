from __future__ import annotations

from html import escape as html_escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.logging_setup import get_logger
from src.packs import service as packs
from src.packs.service import (
    ChannelAlreadyInPackError,
    PackLimitError,
    PackNameTakenError,
    PackNotFoundError,
)

folders_router = Router(name="folders")
log = get_logger(__name__)

NEW_PACK = "fp:new"
BACK_TO_LIST = "fp:list"
CHANNELS_PER_PAGE = 15


class FolderStates(StatesGroup):
    waiting_pack_name = State()
    waiting_pack_rename = State()
    waiting_channel_input = State()
    waiting_search_question = State()


def _pack_cb(pack_id: int, action: str) -> str:
    return f"fp:{pack_id}:{action}"


def _channel_cb(pack_id: int, channel_id: int, action: str) -> str:
    return f"fc:{pack_id}:{channel_id}:{action}"


def _parse_pack_cb(data: str) -> tuple[int, str] | None:
    parts = data.split(":")
    if not parts or parts[0] != "fp":
        return None
    if len(parts) == 2:
        # `fp:new` / `fp:list` — special actions without a pack id.
        return (0, parts[1])
    if len(parts) != 3:
        return None
    if parts[1] in ("new", "list"):
        return (0, parts[2])
    try:
        return (int(parts[1]), parts[2])
    except ValueError:
        return None


def _parse_channel_cb(data: str) -> tuple[int, int, str] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != "fc":
        return None
    try:
        return (int(parts[1]), int(parts[2]), parts[3])
    except ValueError:
        return None


def _list_keyboard(packs_list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in packs_list:
        rows.append([InlineKeyboardButton(text=p.name, callback_data=_pack_cb(p.id, "open"))])
    rows.append([InlineKeyboardButton(text="➕ Новая папка", callback_data=NEW_PACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pack_keyboard(pack_id: int, channels=(), page: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="➕ Канал", callback_data=_pack_cb(pack_id, "add")),
            InlineKeyboardButton(
                text="🔍 Поиск по папке", callback_data=_pack_cb(pack_id, "search")
            ),
        ]
    ]
    start = page * CHANNELS_PER_PAGE
    for channel in channels[start : start + CHANNELS_PER_PAGE]:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📡 {channel.title or channel.telegram_id}",
                    callback_data=_channel_cb(pack_id, channel.id, "open"),
                )
            ]
        )
    pages = max(1, (len(channels) + CHANNELS_PER_PAGE - 1) // CHANNELS_PER_PAGE)
    if pages > 1:
        pagination: list[InlineKeyboardButton] = []
        if page > 0:
            pagination.append(
                InlineKeyboardButton(
                    text="‹",
                    callback_data=_pack_cb(pack_id, f"page_{page - 1}"),
                )
            )
        pagination.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
        if page + 1 < pages:
            pagination.append(
                InlineKeyboardButton(
                    text="›",
                    callback_data=_pack_cb(pack_id, f"page_{page + 1}"),
                )
            )
        rows.append(pagination)
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    text="✏️ Переименовать", callback_data=_pack_cb(pack_id, "rename")
                ),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=_pack_cb(pack_id, "delete")),
            ],
            [InlineKeyboardButton(text="« К папкам", callback_data=BACK_TO_LIST)],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _channel_keyboard(
    pack_id: int, channel_id: int, *, confirm_remove: bool = False
) -> InlineKeyboardMarkup:
    if confirm_remove:
        rows = [
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=_channel_cb(pack_id, channel_id, "remove_yes"),
                ),
                InlineKeyboardButton(
                    text="Отмена", callback_data=_channel_cb(pack_id, channel_id, "open")
                ),
            ]
        ]
    else:
        rows = [
            [
                InlineKeyboardButton(
                    text="🔄 Обновить посты",
                    callback_data=_channel_cb(pack_id, channel_id, "update"),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Удалить из папки",
                    callback_data=_channel_cb(pack_id, channel_id, "remove"),
                )
            ],
        ]
    rows.append([InlineKeyboardButton(text="« К папке", callback_data=_pack_cb(pack_id, "open"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _delete_pack_keyboard(pack_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить папку", callback_data=_pack_cb(pack_id, "delete_yes")
                ),
                InlineKeyboardButton(text="Отмена", callback_data=_pack_cb(pack_id, "open")),
            ]
        ]
    )


def _format_pack_card(pack, channels, page: int = 0) -> str:
    name = html_escape(pack.name)
    desc = f"\n<i>{html_escape(pack.description)}</i>" if pack.description else ""
    if not channels:
        body = f"<b>{name}</b>{desc}\n\n<i>В папке нет каналов.</i>"
    else:
        start = page * CHANNELS_PER_PAGE
        shown = channels[start : start + CHANNELS_PER_PAGE]
        lines = [f"<b>{name}</b>{desc}", "", f"<b>Каналы ({len(channels)}):</b>"]
        for ch in shown:
            mark = "" if ch.last_indexed_message_id else " ⏳"
            lines.append(f"• {html_escape(ch.title or ch.telegram_id)}{mark}")
        body = "\n".join(lines)
    return body


def _format_channel_card(channel) -> str:
    status = (
        f"Последний проиндексированный пост: <code>{channel.last_indexed_message_id}</code>"
        if channel.last_indexed_message_id
        else "<i>Канал ещё не проиндексирован.</i>"
    )
    return (
        f"<b>{html_escape(channel.title or channel.telegram_id)}</b>\n\n"
        f"Идентификатор: <code>{html_escape(channel.telegram_id)}</code>\n"
        f"{status}"
    )


async def _edit_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Edit the callback's message if it is an accessible Message, then ack."""
    msg = callback.message
    if isinstance(msg, Message):
        await msg.edit_text(text, reply_markup=reply_markup)
    await callback.answer()


@folders_router.message(Command("folders"))
async def cmd_folders(message: Message, db_session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        await message.answer("Эта команда доступна только в личке с ботом.")
        return
    await _show_list(message, db_session, user_id)


async def _show_list(
    message_or_callback: Message | CallbackQuery,
    db_session: AsyncSession,
    user_id: int,
) -> None:
    packs_list = await packs.list_packs(db_session, user_id)
    text = "<b>Ваши папки</b>\n\n" + (
        "\n".join(f"• {html_escape(p.name)}" for p in packs_list)
        if packs_list
        else "<i>Пока нет ни одной папки.</i>"
    )
    kb = _list_keyboard(packs_list)
    if isinstance(message_or_callback, CallbackQuery):
        await _edit_callback(message_or_callback, text, kb)
    else:
        await message_or_callback.answer(text, reply_markup=kb)


@folders_router.callback_query(F.data == BACK_TO_LIST)
async def cb_back_to_list(
    callback: CallbackQuery, db_session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    user_id = _user_id(callback)
    if user_id is None:
        await callback.answer()
        return
    await _show_list(callback, db_session, user_id)


@folders_router.callback_query(F.data == NEW_PACK)
async def cb_new_pack(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FolderStates.waiting_pack_name)
    await _edit_callback(callback, "Введи название новой папки (или /cancel для отмены):")


@folders_router.message(Command("cancel"), StateFilter(FolderStates))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено. /folders — к списку папок.")


@folders_router.message(StateFilter(FolderStates.waiting_pack_name), F.text)
async def on_pack_name(message: Message, state: FSMContext, db_session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    name = (message.text or "").strip()
    try:
        pack = await packs.create_pack(db_session, user_id, name)
        await db_session.commit()
    except PackNameTakenError:
        await message.answer("Папка с таким именем уже существует. Введи другое:")
        return
    except PackLimitError as exc:
        await state.clear()
        await message.answer(f"⛔️ {exc}")
        return
    except ValueError:
        await message.answer("Название не может быть пустым. Введи название:")
        return

    await state.clear()
    await _open_pack_card(message, db_session, user_id, pack.id)


@folders_router.callback_query(F.data.startswith("fp:"))
async def cb_pack_action(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    user_id = _user_id(callback)
    if user_id is None:
        await callback.answer()
        return
    parsed = _parse_pack_cb(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    pack_id, action = parsed

    if pack_id == 0:
        await callback.answer()
        return
    pack = await packs.get_pack(db_session, pack_id, user_id)
    if pack is None:
        await state.clear()
        await _edit_callback(callback, "Папка не найдена или была удалена.")
        return

    if action == "open":
        await _open_pack_card(callback, db_session, user_id, pack_id)
    elif action.startswith("page_"):
        try:
            page = max(0, int(action.removeprefix("page_")))
        except ValueError:
            await callback.answer()
            return
        await _open_pack_card(callback, db_session, user_id, pack_id, page=page)
    elif action == "rename":
        await state.set_state(FolderStates.waiting_pack_rename)
        await state.update_data(pack_id=pack_id)
        await _edit_callback(callback, "Введи новое название папки (или /cancel):")
    elif action == "delete":
        await _edit_callback(
            callback,
            f"Удалить папку <b>{html_escape(pack.name)}</b>? Каналы и посты останутся "
            "доступны другим пользователям, если состоят в их папках.",
            _delete_pack_keyboard(pack_id),
        )
    elif action == "delete_yes":
        await state.clear()
        await packs.delete_pack(db_session, pack_id, user_id)
        await db_session.commit()
        await _show_list(callback, db_session, user_id)
    elif action == "add":
        await state.set_state(FolderStates.waiting_channel_input)
        await state.update_data(pack_id=pack_id)
        await _edit_callback(
            callback,
            "Пришли @username канала или перешли пост из него "
            "(я добавлю канал и сразу запущу индексацию).",
        )
    elif action == "search":
        await state.set_state(FolderStates.waiting_search_question)
        await state.update_data(pack_id=pack_id)
        await _edit_callback(callback, "Введи вопрос для поиска по этой папке (или /cancel):")
    else:
        await callback.answer()


@folders_router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@folders_router.callback_query(F.data.startswith("fc:"))
async def cb_channel_action(
    callback: CallbackQuery, state: FSMContext, db_session: AsyncSession
) -> None:
    user_id = _user_id(callback)
    if user_id is None:
        await callback.answer()
        return
    parsed = _parse_channel_cb(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    pack_id, channel_id, action = parsed
    channel = await packs.get_pack_channel(db_session, pack_id, channel_id, owner_id=user_id)
    if channel is None:
        await state.clear()
        await _edit_callback(callback, "Канал или папка не найдены.")
        return

    if action == "open":
        await _open_channel_card(callback, channel, pack_id)
    elif action == "remove":
        await _edit_callback(
            callback,
            f"Удалить <b>{html_escape(channel.title or channel.telegram_id)}</b> из папки? "
            "Если это последний канал, папка тоже будет удалена.",
            _channel_keyboard(pack_id, channel_id, confirm_remove=True),
        )
    elif action == "remove_yes":
        result = await packs.remove_channel_from_pack(
            db_session, pack_id, channel_id, owner_id=user_id
        )
        await db_session.commit()
        await state.clear()
        if result.pack_deleted:
            await _show_list(callback, db_session, user_id)
        else:
            await _open_pack_card(callback, db_session, user_id, pack_id)
    elif action == "update":
        await callback.answer("Обновляю канал")
        msg = callback.message
        if isinstance(msg, Message):
            await msg.edit_text(
                f"Обновляю <b>{html_escape(channel.title or channel.telegram_id)}</b>…"
            )
        try:
            created = await _index_channel_now(db_session, channel)
        except Exception as exc:
            await db_session.rollback()
            log.error(
                "folders.channel_update.error",
                channel_id=channel.id,
                error=str(exc),
            )
            if isinstance(msg, Message):
                await msg.edit_text(
                    "Не удалось обновить канал. Проверьте доступ Telegram-сессии и "
                    "повторите позже.",
                    reply_markup=_channel_keyboard(pack_id, channel_id),
                )
            return
        refreshed = await packs.get_pack_channel(db_session, pack_id, channel_id, owner_id=user_id)
        if refreshed is not None and isinstance(msg, Message):
            await msg.edit_text(
                f"{_format_channel_card(refreshed)}\n\nДобавлено новых постов: <b>{created}</b>",
                reply_markup=_channel_keyboard(pack_id, channel_id),
            )
    else:
        await callback.answer()


@folders_router.message(StateFilter(FolderStates.waiting_pack_rename), F.text)
async def on_pack_rename(message: Message, state: FSMContext, db_session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    data = await state.get_data()
    pack_id = int(data.get("pack_id", 0))
    if not pack_id:
        await state.clear()
        return
    name = (message.text or "").strip()
    try:
        pack = await packs.rename_pack(db_session, pack_id, user_id, name)
        await db_session.commit()
    except PackNotFoundError:
        await state.clear()
        await message.answer("Папка не найдена.")
        return
    except PackNameTakenError:
        await message.answer("Такое имя уже занято. Введи другое:")
        return
    except ValueError:
        await message.answer("Название не может быть пустым. Введи название:")
        return

    await state.clear()
    await _open_pack_card(message, db_session, user_id, pack.id)


@folders_router.message(StateFilter(FolderStates.waiting_channel_input))
async def on_channel_input(message: Message, state: FSMContext, db_session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    data = await state.get_data()
    pack_id = int(data.get("pack_id", 0))
    if not pack_id:
        await state.clear()
        return

    telegram_id, username = _extract_channel_ref(message)
    if telegram_id is None:
        await message.answer(
            "Не понял, какой канал. Пришли @username или перешли пост из канала. Или /cancel."
        )
        return

    try:
        channel = await packs.ensure_channel(db_session, telegram_id=telegram_id, username=username)
        await packs.add_channel_to_pack(db_session, pack_id, channel.id, owner_id=user_id)
        await db_session.commit()
    except ChannelAlreadyInPackError:
        await state.clear()
        await message.answer("Этот канал уже в папке.")
        await _open_pack_card(message, db_session, user_id, pack_id)
        return
    except PackLimitError as exc:
        await state.clear()
        await message.answer(f"⛔️ {exc}")
        await _open_pack_card(message, db_session, user_id, pack_id)
        return
    except PackNotFoundError:
        await state.clear()
        await message.answer("Папка не найдена или была удалена.")
        return

    await state.clear()
    await message.answer(
        f"Канал {html_escape(channel.title or channel.telegram_id)} добавлен. "
        "Индексирую доступную историю…"
    )
    try:
        created = await _index_channel_now(db_session, channel)
    except Exception as exc:
        await db_session.rollback()
        log.error(
            "folders.channel_add.index_error",
            channel_id=channel.id,
            error=str(exc),
        )
        await message.answer(
            "Канал сохранён, но индексация не удалась. Открой его карточку и нажми "
            "«Обновить посты» позже."
        )
    else:
        await message.answer(f"Индексация завершена. Добавлено постов: <b>{created}</b>.")
    await _open_pack_card(message, db_session, user_id, pack_id)


@folders_router.message(StateFilter(FolderStates.waiting_search_question), F.text)
async def on_search_question(message: Message, state: FSMContext, db_session: AsyncSession) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    data = await state.get_data()
    pack_id = int(data.get("pack_id", 0))
    if not pack_id:
        await state.clear()
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Вопрос пустой. Введи вопрос или /cancel.")
        return

    await state.clear()
    await _run_pack_search(message, db_session, user_id, pack_id, question)


async def _run_pack_search(
    message: Message,
    db_session: AsyncSession,
    user_id: int,
    pack_id: int,
    question: str,
) -> None:
    from src.bot.handlers.search import format_answer_for_message
    from src.search.answerer import PostAnswerer
    from src.search.llm import get_llm_client
    from src.search.selector import TitleSelector

    channel_ids = await packs.get_pack_channel_ids(db_session, pack_id, owner_id=user_id)
    if not channel_ids:
        await message.answer("В папке нет каналов для поиска.")
        return

    await message.answer("🔍 Ищу по каналам папки…")

    llm = get_llm_client()
    answerer = PostAnswerer(selector=TitleSelector(llm=llm), llm=llm)
    try:
        answer = await answerer.answer(db_session, question, channel_ids=channel_ids)
    except Exception as exc:
        log.error("folders.search.error", error=str(exc), question=question)
        await message.answer("⚠️ Ошибка при поиске. Попробуйте позже.")
        return

    text = format_answer_for_message(answer)
    await message.answer(text, disable_web_page_preview=True)


async def _open_pack_card(
    target: Message | CallbackQuery,
    db_session: AsyncSession,
    user_id: int,
    pack_id: int,
    page: int = 0,
) -> None:
    pack = await packs.get_pack(db_session, pack_id, user_id)
    if pack is None:
        text = "Папка не найдена."
        if isinstance(target, CallbackQuery):
            await _edit_callback(target, text)
        else:
            await target.answer(text)
        return
    channels = await packs.list_pack_channels(db_session, pack_id, owner_id=user_id)
    max_page = max(0, (len(channels) - 1) // CHANNELS_PER_PAGE)
    page = min(page, max_page)
    text = _format_pack_card(pack, channels, page)
    kb = _pack_keyboard(pack_id, channels, page)
    if isinstance(target, CallbackQuery):
        await _edit_callback(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _open_channel_card(
    target: Message | CallbackQuery,
    channel,
    pack_id: int,
) -> None:
    text = _format_channel_card(channel)
    keyboard = _channel_keyboard(pack_id, channel.id)
    if isinstance(target, CallbackQuery):
        await _edit_callback(target, text, keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


async def _index_channel_now(db_session: AsyncSession, channel) -> int:
    from src.indexer.pipeline import index_channel
    from src.parser.client import TelethonParser, get_telethon_client

    client = get_telethon_client()
    await client.start()
    try:
        parser = TelethonParser(client)
        channel_ref = f"@{channel.username}" if channel.username else channel.telegram_id
        _, created = await index_channel(db_session, parser, channel_ref)
        return created
    finally:
        await client.disconnect()


def _user_id(event: Message | CallbackQuery) -> int | None:
    user = getattr(event, "from_user", None)
    if user is None and isinstance(event, Message):
        user = event.from_user
    if user is None:
        return None
    return user.id


def _extract_channel_ref(message: Message) -> tuple[str | None, str | None]:
    """Return (telegram_id, username) from a forwarded post or @username text.

    telegram_id is what we store in channels.telegram_id; for public channels
    that's the @username; for private ones the -100... id from forward origin.
    """
    fwd = message.forward_origin
    if fwd is not None:
        chat = getattr(fwd, "chat", None) or getattr(fwd, "sender_chat", None)
        if chat is not None:
            username = getattr(chat, "username", None)
            if username:
                uname = packs.normalize_username(f"@{username}")
                return (uname or f"@{username}", username)
            chat_id = getattr(chat, "id", None)
            if chat_id is not None:
                return (str(chat_id), None)

    text = (message.text or "").strip()
    uname = packs.normalize_username(text)
    if uname is not None:
        return (uname, uname[1:])
    return (None, None)
