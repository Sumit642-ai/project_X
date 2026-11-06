"""Contact confidence: score = recency x source reliability x last outcome.

The factor tables are calibrated against annex.md Sheet 8 so the hero ladders reproduce
(Raymond exactly; others within 0.02). A disconnected outcome always drops the number below
0.1 (capped at 0.09). Third parties without authorisation are stored but never callable.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

RECENCY_BANDS: tuple[tuple[int, float], ...] = (  # (max age in days, factor)
    (30, 1.0),
    (180, 0.875),
    (365, 0.85),
    (730, 0.625),
)
RECENCY_OLDER = 0.46
RECENCY_UNKNOWN = 0.60  # never verified

SOURCE_RELIABILITY: dict[str, float] = {
    "discharge summary": 0.94,
    "eligibility": 0.95,
    "pharmacy": 0.90,
    "representative form": 0.85,
    "cm note": 0.80,
}
SOURCE_DEFAULT = 0.70

OUTCOME: dict[str | None, float] = {
    "answered": 1.0,
    "voicemail": 1.0,  # the line is live and reaches the right mailbox
    "answered_pharmacy_ivr": 0.91,
    "no_answer": 0.80,
    "not_tried": 0.80,
    None: 0.80,
    "disconnected": 0.10,
}
DISCONNECTED_CAP = Decimal("0.09")


@dataclass(frozen=True)
class ContactScore:
    confidence: Decimal
    recency: float
    reliability: float
    outcome: float
    age_days: int | None

    def factors(self) -> dict[str, object]:
        return {
            "recency": self.recency,
            "reliability": self.reliability,
            "outcome": self.outcome,
            "age_days": self.age_days,
            "formula": "recency x reliability x outcome",
        }


def source_kind(source: str | None) -> str | None:
    text = (source or "").lower()
    for kind in ("discharge summary", "pharmacy", "representative form", "eligibility"):
        if kind in text:
            return kind
    if "cm note" in text:
        return "cm note"
    return None


def recency_factor(last_verified: date | None, today: date) -> tuple[float, int | None]:
    if last_verified is None:
        return RECENCY_UNKNOWN, None
    age = (today - last_verified).days
    for limit, factor in RECENCY_BANDS:
        if age <= limit:
            return factor, age
    return RECENCY_OLDER, age


def contact_confidence(
    source: str | None, last_verified: date | None, last_outcome: str | None, today: date
) -> ContactScore:
    recency, age = recency_factor(last_verified, today)
    reliability = SOURCE_RELIABILITY.get(source_kind(source) or "", SOURCE_DEFAULT)
    outcome = OUTCOME.get(last_outcome, OUTCOME[None])
    raw = Decimal(str(recency * reliability * outcome))
    score = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if last_outcome == "disconnected":
        score = min(score, DISCONNECTED_CAP)
    return ContactScore(score, recency, reliability, outcome, age)
