from __future__ import annotations

from src.search.confidence import ConfidenceLevel, classify_confidence


def test_high_confidence() -> None:
    assert classify_confidence(0.95) is ConfidenceLevel.HIGH
    assert classify_confidence(0.7).value == "high"


def test_medium_confidence() -> None:
    assert classify_confidence(0.5) is ConfidenceLevel.MEDIUM
    assert classify_confidence(0.4).value == "medium"


def test_low_confidence() -> None:
    assert classify_confidence(0.1) is ConfidenceLevel.LOW
    assert classify_confidence(0.0).value == "low"


def test_boundary_high() -> None:
    assert classify_confidence(0.7) is ConfidenceLevel.HIGH


def test_just_below_medium_is_low() -> None:
    assert classify_confidence(0.399) is ConfidenceLevel.LOW
