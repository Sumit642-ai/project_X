"""Call transcripts as numbered speaker turns: `12. MEMBER: text`.

The MVP has no live speech-to-text. A call's transcript is the synthetic file for the member in
data/seed/transcripts/, standing in for the telephony vendor's transcription feed.
"""

import re
from dataclasses import dataclass
from pathlib import Path

SPEAKERS = ("NURSE", "MEMBER", "CAREGIVER")
TURN = re.compile(rf"^\s*(\d+)\.\s+({'|'.join(SPEAKERS)}):\s*(.*?)\s*$")


@dataclass(frozen=True)
class Turn:
    number: int
    speaker: str
    text: str


class TranscriptError(ValueError):
    pass


def parse_transcript(text: str) -> list[Turn]:
    """Lines that do not start a turn continue the previous one. Numbers must increase."""
    turns: list[Turn] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = TURN.match(line)
        if match:
            number = int(match.group(1))
            if turns and number <= turns[-1].number:
                raise TranscriptError(f"turn {number} follows turn {turns[-1].number}")
            turns.append(Turn(number, match.group(2), match.group(3)))
        elif turns:
            last = turns[-1]
            turns[-1] = Turn(last.number, last.speaker, f"{last.text} {line.strip()}")
        else:
            raise TranscriptError(f"text before the first turn: {line.strip()[:40]}")
    return turns


def load_transcript(directory: Path, member_id: str) -> list[Turn] | None:
    path = directory / f"{member_id}.txt"
    if not path.is_file():
        return None
    return parse_transcript(path.read_text(encoding="utf-8"))


def render(turns: list[Turn]) -> str:
    return "\n".join(f"{t.number}. {t.speaker}: {t.text}" for t in turns)
