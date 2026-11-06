"""Checks run on every draft after the model call, whatever the prompt said.

- A sentence that cites no turn, or cites a turn the transcript does not have, is UNSUPPORTED.
- A sentence that reads as a dose instruction, a diagnosis or a coverage statement is BLOCKED
  (the prompt forbids them; this is the backstop).
- Medication names that appear in neither the transcript nor the member's medication Facts are
  flagged on the sentence and on the draft.

Only supported sentences go into the text the nurse can insert into their note.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.ai_draft.client import DraftUnavailableError
from app.ai_draft.medications import medication_mentions
from app.ai_draft.provenance import AiDrafted
from app.ai_draft.transcript import Turn

Status = Literal["supported", "unsupported", "blocked"]
Section = Literal["summary", "note"]


class RawSentence(BaseModel):
    text: str
    source_turns: list[int] = []


class RawDraft(BaseModel):
    summary_sentences: list[RawSentence]
    suggested_note: list[RawSentence]
    open_questions: list[str] = []


def parse_output(text: str) -> RawDraft:
    try:
        return RawDraft.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise DraftUnavailableError("invalid_output", str(exc)[:300]) from exc


DOSE_INSTRUCTION = re.compile(
    r"\b(increase|decrease|reduce|raise|lower|double|halve|titrate|adjust|change)\b[^.]{0,60}"
    r"\b(dose|dosage|\d+(\.\d+)?\s*(mg|mcg|milligrams?|ml|units?|puffs?|tablets?))\b"
    r"|\b(should|must|needs? to|recommend(s|ed)?|advise(s|d)?)\b[^.]{0,40}"
    r"\b(take|dose|dosage|mg|mcg|milligrams?)\b",
    re.IGNORECASE,
)
DIAGNOSIS = re.compile(
    r"\b(diagnos(is|es|ed|e|ing)|likely has|consistent with|suggestive of|indicative of)\b",
    re.IGNORECASE,
)
COVERAGE = re.compile(
    r"\b(is|are|will be|would be|isn't|aren't|is not|are not|won't be|not)\s+(fully\s+)?covered\b"
    r"|\b(plan|insurance|medicaid|medicare)\s+(covers|pays for|will cover|will pay|won't cover|"
    r"won't pay|does not cover|doesn't cover|approved|denied)\b"
    r"|\b(prior authori[sz]ation|claim)\s+(was|is|will be)\s+(approved|denied)\b",
    re.IGNORECASE,
)
REPORTED_QUESTION = re.compile(r"\b(asked|asks|whether)\b|\?", re.IGNORECASE)


def prohibited(text: str) -> list[str]:
    reasons = []
    if DOSE_INSTRUCTION.search(text):
        reasons.append("dose recommendation")
    if DIAGNOSIS.search(text):
        reasons.append("diagnosis")
    if COVERAGE.search(text) and not REPORTED_QUESTION.search(text):
        reasons.append("coverage statement")
    return reasons


@dataclass
class CheckedSentence:
    section: Section
    text: str
    source_turns: list[int]
    status: Status
    reasons: list[str] = field(default_factory=list)
    flagged_medications: list[str] = field(default_factory=list)


@dataclass
class CheckedDraft:
    sentences: list[CheckedSentence]
    open_questions: list[str]
    flagged_medications: list[str]

    @property
    def unsupported_count(self) -> int:
        return sum(1 for s in self.sentences if s.status == "unsupported")

    @property
    def blocked_count(self) -> int:
        return sum(1 for s in self.sentences if s.status == "blocked")

    @property
    def note_text(self) -> AiDrafted:
        """What "Insert into my notes" inserts: supported note sentences only."""
        return AiDrafted(
            " ".join(
                s.text for s in self.sentences if s.section == "note" and s.status == "supported"
            )
        )


def check_sentence(
    section: Section, raw: RawSentence, turn_numbers: set[int], known: set[str]
) -> CheckedSentence:
    text = raw.text.strip()
    cited = sorted(set(raw.source_turns))
    reasons = []
    if not cited:
        reasons.append("cites no transcript turn")
    missing = [n for n in cited if n not in turn_numbers]
    if missing:
        reasons.append(f"cites turns not in the transcript: {', '.join(map(str, missing))}")
    blocked = prohibited(text)
    status: Status = "blocked" if blocked else "unsupported" if reasons else "supported"
    return CheckedSentence(
        section,
        AiDrafted(text),
        cited,
        status,
        blocked + reasons,
        sorted(medication_mentions(text) - known),
    )


def check_draft(raw: RawDraft, turns: list[Turn], known_terms: set[str]) -> CheckedDraft:
    numbers = {t.number for t in turns}
    sections: list[tuple[Section, list[RawSentence]]] = [
        ("summary", raw.summary_sentences),
        ("note", raw.suggested_note),
    ]
    sentences = [
        check_sentence(section, sentence, numbers, known_terms)
        for section, items in sections
        for sentence in items
        if sentence.text.strip()
    ]
    questions: list[str] = [AiDrafted(q.strip()) for q in raw.open_questions if q.strip()]
    flagged = {m for s in sentences for m in s.flagged_medications}
    for question in questions:
        flagged |= medication_mentions(question) - known_terms
    return CheckedDraft(sentences, questions, sorted(flagged))
