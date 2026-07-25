from __future__ import annotations

from src.parser.extract import extract_hashtags, extract_title


def test_title_first_paragraph() -> None:
    text = "Первый абзац.\n\nВторой абзац длиннее."
    assert extract_title(text) == "Первый абзац."


def test_title_skips_hashtag_only_paragraph() -> None:
    text = "#ai #news 🔥\n\nНастоящий заголовок поста"
    assert extract_title(text) == "Настоящий заголовок поста"


def test_title_single_line() -> None:
    assert extract_title("Одна строка без абзацев") == "Одна строка без абзацев"


def test_title_empty() -> None:
    assert extract_title("") == ""
    assert extract_title("   ") == ""


def test_title_collapses_internal_newlines() -> None:
    text = "Строка один\nстрока два\n\nДругой абзац"
    assert extract_title(text) == "Строка один строка два"


def test_title_truncates_on_word_boundary() -> None:
    text = "слово " * 50
    title = extract_title(text, max_len=20)
    assert len(title) <= 21  # room for ellipsis
    assert title.endswith("…")
    assert "  " not in title


def test_hashtags_unique_lowercase_order() -> None:
    text = "Тема #AI и снова #ai потом #News #AI"
    assert extract_hashtags(text) == ["#ai", "#news"]


def test_hashtags_cyrillic() -> None:
    text = "Пост #ИИ #новости"
    assert extract_hashtags(text) == ["#ии", "#новости"]


def test_hashtags_empty() -> None:
    assert extract_hashtags("") == []
    assert extract_hashtags("без тегов") == []
