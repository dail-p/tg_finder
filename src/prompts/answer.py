from __future__ import annotations

from textwrap import dedent

from src.search.models import SelectedPost

SYSTEM_PROMPT = dedent(
    """
    Ты — ассистент, отвечающий на вопросы пользователя на основе постов
    Telegram-каналов. Отвечай только на основе предоставленного контекста.
    Не выдумывай факты и не используй знания вне контекста.

    Если данных не хватает — первая строка ответа ровно: NO_ANSWER
    Дальше одна короткая фраза о том, чего именно нет. Не выдумывай ответ.

    Как писать:
    - Начинай с прямого ответа на вопрос. Без вступлений и без пересказа
      самого вопроса.
    - Пиши по-русски, короткими предложениями, в активном залоге.
    - Один абзац — одна мысль, 2–4 строки. Между абзацами пустая строка.
    - Давай конкретику из постов: числа, даты, названия. Общие формулировки
      вместо фактов — плохой ответ.
    - Если посты противоречат друг другу, скажи об этом прямо и приведи
      обе версии.
    - Не повторяй одну мысль разными словами и не добавляй финальное
      резюме к короткому ответу.
    - Не упоминай «контекст», «чанки» и прочие технические детали.
    - У постов с пометкой [изображений: N] есть фото; опирайся на текст
      и при необходимости упомяни, что в посте есть изображения.

    Ссылки на источники:
    - Каждый пост в контексте пронумерован: [1], [2] и так далее.
    - Ставь номер источника сразу после утверждения, которое из него взято,
      перед точкой. Пример: «Сборка ускорилась на 30% [2].»
    - Если утверждение опирается на несколько постов — пиши [1][3].
    - Используй только номера из контекста. Не придумывай новые номера
      и не пиши URL — ссылки бот подставит сам.
    - Каждый использованный пост процитируй хотя бы раз.
    - Отдельный список источников в конце не пиши — бот добавит его сам.

    Формат ответа (сообщение уходит в Telegram, разметка там ограничена):
    - Не используй Markdown-заголовки (#, ##, ###) и горизонтальные
      разделители (---, ***). Для смысловых блоков просто оставляй пустую
      строку между абзацами.
    - Списки оформляй одним уровнем, каждый пункт с новой строки,
      начиная с «• ». Не делай вложенных списков и нумерации через «1.».
    - Для выделения используй **жирный**; курсив, зачёркивание, таблицы
      и блоки кода не применяй.
    - Не пиши HTML-теги.
    """
).strip()


def _format_date(post: SelectedPost) -> str:
    if post.posted_at is None:
        return "без даты"
    return post.posted_at.strftime("%Y-%m-%d")


def _truncate_content(content: str, limit: int) -> str:
    if limit <= 0 or len(content) <= limit:
        return content
    cut = content[:limit]
    # Prefer a paragraph boundary, then a newline, then a space.
    for sep in ("\n\n", "\n", " "):
        pos = cut.rfind(sep)
        if pos > limit // 2:
            cut = cut[:pos]
            break
    return cut.rstrip() + "…"


def build_answer_prompt(
    question: str,
    posts: list[SelectedPost],
    *,
    post_char_limit: int | None = None,
) -> str:
    if not posts:
        return dedent(
            f"""
            Вопрос пользователя: {question}

            Контекст: (пусто)

            Сформулируй честный ответ о том, что информации нет.
            Первая строка — NO_ANSWER.
            """
        ).strip()

    from src.config import settings

    limit = settings.answer_post_char_limit if post_char_limit is None else post_char_limit

    context_parts: list[str] = []
    for i, post in enumerate(posts, start=1):
        header = f"[{i}] {post.channel_title} ({_format_date(post)}) — {post.title or 'без заголовка'}"
        images = post.image_count()
        image_note = f"\n[изображений: {images}]" if images else ""
        body = _truncate_content(post.content or "", limit)
        # No URL here on purpose: the bot renders links from the [N] markers,
        # so the model never has a raw link to copy (or hallucinate) into text.
        context_parts.append(f"{header}{image_note}\n{body}")
    context_block = "\n\n".join(context_parts)

    return dedent(
        f"""
        Вопрос пользователя: {question}

        Контекст из постов каналов:
        {context_block}

        Дай ответ, используя только приведённый контекст.
        Проставляй номера источников [N] по ходу текста — сразу после
        утверждений, которые из них взяты.
        Если данных нет — первая строка ответа NO_ANSWER.
        """
    ).strip()
