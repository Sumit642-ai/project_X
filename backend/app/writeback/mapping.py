"""Declarative field mapping (mapping.yaml) between CaseCompass and the CM platform.

AI-drafted text may only be written to fields marked `ai: allowed` (the note body). The mapping
enforces this itself, so no caller (UI, API or future code) can route a draft into a
medication, allergy, dose or assessment field.
"""

import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.ai_draft.provenance import contains_ai_text

MAPPING_FILE = Path(__file__).with_name("mapping.yaml")
SECTIONS = ("note", "assessment", "task")


class AiWriteForbiddenError(ValueError):
    def __init__(self, fields: list[str]) -> None:
        super().__init__(
            "AI-drafted text can only go in the free-text note, not: " + ", ".join(fields)
        )
        self.fields = fields


@dataclass(frozen=True)
class FieldMap:
    section: str
    ours: str
    theirs: str
    type: str = "str"
    ai_allowed: bool = False

    def encode(self, value: Any) -> Any:
        if value is None:
            return None
        if self.type == "datetime":
            return value.isoformat() if isinstance(value, datetime) else str(value)
        if self.type == "date":
            return value.isoformat() if isinstance(value, date) else str(value)
        if self.type == "bool":
            return bool(value)
        if self.type == "json":
            return json.dumps(value, sort_keys=True, default=str)
        return str(value)

    def decode(self, value: Any) -> Any:
        if value is None:
            return None
        if self.type == "datetime":
            return datetime.fromisoformat(value)
        if self.type == "date":
            return date.fromisoformat(value)
        if self.type == "bool":
            return bool(value)
        if self.type == "json":
            return json.loads(value)
        return str(value)


@lru_cache
def load_mapping(path: Path = MAPPING_FILE) -> dict[str, tuple[FieldMap, ...]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        section: tuple(
            FieldMap(
                section, e["ours"], e["theirs"], e.get("type", "str"), e.get("ai") == "allowed"
            )
            for e in data[section]
        )
        for section in SECTIONS
    }


def encode_section(
    section: str, ours: dict[str, Any], ai_sourced: Collection[str] = ()
) -> dict[str, Any]:
    """Our values -> CM field names. Only mapped fields present in `ours` are sent.

    `ai_sourced` names our fields whose value came from the AI draft. Those, and any value that
    is AiDrafted text, are refused unless the target field is `ai: allowed`.
    """
    mapped = [m for m in load_mapping()[section] if m.ours in ours]
    forbidden = [
        f"{section}.{m.ours}"
        for m in mapped
        if not m.ai_allowed and (m.ours in ai_sourced or contains_ai_text(ours[m.ours]))
    ]
    if forbidden:
        raise AiWriteForbiddenError(forbidden)
    return {m.theirs: m.encode(ours[m.ours]) for m in mapped}


def decode_section(section: str, theirs: dict[str, Any]) -> dict[str, Any]:
    return {
        m.ours: m.decode(theirs[m.theirs]) for m in load_mapping()[section] if m.theirs in theirs
    }
