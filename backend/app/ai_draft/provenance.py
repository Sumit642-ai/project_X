"""Marks text that came from the AI draft, so the write-back mapping can refuse it anywhere but
the free-text note (app/writeback/mapping.py)."""

from typing import Any


class AiDrafted(str):
    """A str written by the drafting model. Behaves as a str; only its type records origin."""

    __slots__ = ()


def contains_ai_text(value: Any) -> bool:
    if isinstance(value, AiDrafted):
        return True
    if isinstance(value, dict):
        return any(contains_ai_text(k) or contains_ai_text(v) for k, v in value.items())
    if isinstance(value, list | tuple | set):
        return any(contains_ai_text(v) for v in value)
    return False


def normalise(text: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def flatten(value: Any) -> str:
    """Every string inside a stored answer, joined, for matching against drafted sentences."""
    if isinstance(value, dict):
        return " ".join(flatten(v) for v in value.values())
    if isinstance(value, list | tuple):
        return " ".join(flatten(v) for v in value)
    return "" if value is None else str(value)
