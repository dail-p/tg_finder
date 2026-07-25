from __future__ import annotations

import re

from src.config import settings

HASHTAG_RE = re.compile(r"(?<!\w)#([^\W\d_][\w_]{0,63})", re.UNICODE)

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_WHITESPACE_RE = re.compile(r"\s+")
# A paragraph that carries no words of its own: hashtags, emoji, punctuation.
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


def _is_meaningful(paragraph: str) -> bool:
    """True when a paragraph has text left after stripping hashtags.

    Channels often open a post with a line of tags/emoji; such a paragraph is a
    poor title, so it is skipped in favour of the next one.
    """
    without_tags = HASHTAG_RE.sub(" ", paragraph)
    return bool(_WORD_RE.search(without_tags))


def _truncate(text: str, max_len: int) -> str:
    if max_len <= 0 or len(text) <= max_len:
        return text
    cut = text[:max_len]
    space = cut.rfind(" ")
    if space > max_len // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def extract_title(content: str, max_len: int | None = None) -> str:
    """Return the first meaningful paragraph of a post, trimmed to ``max_len``."""
    if not content or not content.strip():
        return ""

    limit = settings.title_max_len if max_len is None else max_len

    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(content.strip())]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return ""

    chosen = next((p for p in paragraphs if _is_meaningful(p)), paragraphs[0])
    # Single-line texts have no paragraph structure: the first line is the title.
    flattened = _WHITESPACE_RE.sub(" ", chosen).strip()
    return _truncate(flattened, limit)


def extract_hashtags(content: str) -> list[str]:
    """Return unique lowercase hashtags (with ``#``) in order of appearance."""
    if not content:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in HASHTAG_RE.finditer(content):
        tag = "#" + match.group(1).lower()
        if tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
