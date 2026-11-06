"""In-memory dataset the hero and background generators fill before anything is written."""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any

from app.synth.catalog import TZ
from app.synth.ccda_builder import CcdaDocument
from app.synth.hl7_builder import AdtEvent
from app.synth.layouts import LAYOUT_BY_STREAM, LAYOUTS


@dataclass(frozen=True)
class Imperfection:
    id: str
    hero: str
    title: str
    feeds: tuple[str, ...]
    background: bool = True  # also planted in ~10% of background members


# annex.md Sheet 10.
IMPERFECTIONS: tuple[Imperfection, ...] = (
    Imperfection("I-01", "SYN-001", "Hospital-created duplicate record", ("adt", "documents")),
    Imperfection(
        "I-02", "SYN-001", "Discharge dose differs from pharmacy fill", ("documents", "pharmacy")
    ),
    Imperfection(
        "I-03", "SYN-001", "Maintenance drug ran out before admission", ("pharmacy", "adt")
    ),
    Imperfection("I-04", "SYN-001", "Discharge summary requested, never received", ("documents",)),
    Imperfection(
        "I-05", "SYN-001", "ADT without diagnosis; inpatient claim missing", ("adt", "claims")
    ),
    Imperfection(
        "I-06",
        "SYN-002",
        "Apparent refill gap is a non-formulary reject",
        ("pharmacy", "formulary"),
    ),
    Imperfection(
        "I-07",
        "SYN-002",
        "PCP visit not in claims; inferred from new prescription",
        ("pharmacy", "claims"),
    ),
    Imperfection(
        "I-08",
        "SYN-002",
        "English voicemails to a non-English speaker",
        ("cm_platform", "eligibility"),
    ),
    Imperfection(
        "I-09",
        "SYN-003",
        "Disconnected number; newer one on pharmacy profile",
        ("cm_platform", "pharmacy", "eligibility"),
    ),
    Imperfection("I-10", "SYN-003", "ED visits only in ADT, not in claims", ("adt", "claims")),
    Imperfection("I-11", "SYN-003", "No SMS consent on the new number", ("cm_platform",)),
    Imperfection(
        "I-12",
        "SYN-004",
        "Part 2 counselling notes vs visible primary-care buprenorphine",
        ("part2", "pharmacy"),
        background=False,
    ),
    Imperfection(
        "I-13",
        "SYN-004",
        "Housing screen stale and now wrong",
        ("sdoh", "documents", "cm_platform"),
    ),
    Imperfection("I-14", "SYN-004", "Maiden-name duplicate eligibility record", ("eligibility",)),
    Imperfection("I-15", "SYN-005", "Representative form expired", ("eligibility", "cm_platform")),
    Imperfection(
        "I-16", "SYN-005", "LTSS file 32 days old (file-level lag)", ("medicaid",), background=False
    ),
    Imperfection("I-17", "SYN-005", "Authorisation past its decision date", ("um",)),
)
IMPERFECTION_BY_ID = {i.id: i for i in IMPERFECTIONS}

# Every 555-01xx number the annex assigns to a hero or a hero's contact.
HERO_PHONES = (
    "555-0110",
    "555-0121",
    "555-0133",
    "555-0134",
    "555-0142",
    "555-0143",
    "555-0155",
    "555-0160",
    "555-0161",
    "555-0177",
    "555-0188",
)


def at(day: date, hh: int = 0, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ)


class PhonePool:
    """Hands out unused 555-01xx numbers in a seeded order."""

    def __init__(self, rng: random.Random) -> None:
        self._free = [f"555-01{n:02d}" for n in range(100) if f"555-01{n:02d}" not in HERO_PHONES]
        rng.shuffle(self._free)

    def take(self) -> str:
        if not self._free:
            raise RuntimeError("555-01xx phone pool exhausted")
        return self._free.pop(0)


@dataclass
class Dataset:
    rows: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {layout.stream: [] for layout in LAYOUTS}
    )
    adt: list[AdtEvent] = field(default_factory=list)
    documents: list[CcdaDocument] = field(default_factory=list)
    planted: dict[str, dict[str, list[str]]] = field(
        default_factory=lambda: {i.id: {"hero": [], "background": []} for i in IMPERFECTIONS}
    )
    absent: list[dict[str, str]] = field(default_factory=list)
    _counters: dict[str, int] = field(default_factory=dict)

    def next_id(self, prefix: str, width: int = 6) -> str:
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        return f"SYN-{prefix}-{self._counters[prefix]:0{width}d}"

    def add(self, stream: str, **values: Any) -> dict[str, Any]:
        columns = LAYOUT_BY_STREAM[stream].columns
        unknown = set(values) - set(columns)
        if unknown:
            raise KeyError(f"{stream}: unknown columns {sorted(unknown)}")
        row = {column: values.get(column) for column in columns}
        self.rows[stream].append(row)
        return row

    def plant(self, imperfection_id: str, member_id: str, *, hero: bool) -> None:
        bucket = self.planted[imperfection_id]["hero" if hero else "background"]
        if member_id not in bucket:
            bucket.append(member_id)

    def mark_absent(self, member_id: str, feed: str, record: str, imperfection: str) -> None:
        self.absent.append(
            {"member_id": member_id, "feed": feed, "record": record, "imperfection": imperfection}
        )
