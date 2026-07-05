from __future__ import annotations

from enum import StrEnum


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def classify_confidence(score: float) -> ConfidenceLevel:
    from src.config import settings

    if score >= settings.high_confidence:
        return ConfidenceLevel.HIGH
    if score >= settings.medium_confidence:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW
