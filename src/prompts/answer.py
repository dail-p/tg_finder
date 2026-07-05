from __future__ import annotations

from textwrap import dedent

from src.search.models import RetrievedChunk

SYSTEM_PROMPT = dedent(
    """
    Ты — ассистент, отвечающий на вопросы пользователя на основе постов
    Telegram-каналов. Отвечай только на основе предоставленного контекста.
    Не выдумывай факты и не используй знания вне контекста.

    Правила:
    - Если в контексте достаточно информации — дай структурированный, краткий
      и точный ответ на русском языке.
    - Если информации недостаточно или её нет — обязательно напиши:
      «К сожалению, в проиндексированных каналах нет информации по вашему вопросу.»
      и не выдумывай ответ.
    - В конце ответа добавь нумерованный список ссылок на посты-источники.
    - Не упоминай «контекст», «чанки» и технические детали в ответе.
    """
).strip()


def build_answer_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return dedent(
            f"""
            Вопрос пользователя: {question}

            Контекст: (пусто)

            Сформулируй честный ответ о том, что информации нет.
            """
        ).strip()

    context_parts: list[str] = []
    for i, ch in enumerate(chunks, start=1):
        context_parts.append(
            f"[{i}] Источник: {ch.channel_title} ({ch.to_link()})\n{ch.content}"
        )
    context_block = "\n\n".join(context_parts)

    return dedent(
        f"""
        Вопрос пользователя: {question}

        Контекст из постов каналов:
        {context_block}

        Дай ответ, используя только приведённый контекст. В конце добавь список
        ссылок на источники в формате Markdown.
        """
    ).strip()
