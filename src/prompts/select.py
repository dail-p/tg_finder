from __future__ import annotations

from textwrap import dedent

SYSTEM_PROMPT = dedent(
    """
    Ты отбираешь посты по теме вопроса. Тебе дан список заголовков в формате
    "id | канал | дата | заголовок | хештеги". Верни СТРОГО JSON
    {"post_ids": [...]} с id постов, которые могут содержать ответ.
    Не придумывай id, используй только те, что есть в списке.
    Если подходящих нет — верни {"post_ids": []}.
    Лучше включить сомнительный пост, чем пропустить релевантный.
    """
).strip()


def build_select_prompt(question: str, lines: list[str]) -> str:
    listing = "\n".join(lines) if lines else "(пусто)"
    return dedent(
        f"""
        Вопрос пользователя: {question}

        Заголовки постов:
        {listing}

        Верни JSON {{"post_ids": [...]}} только с id из списка выше.
        """
    ).strip()
