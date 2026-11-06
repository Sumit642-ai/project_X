"""Explicit UNKNOWN values. Missing data is never None, "none" or 0 in a member view."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.ingest.freshness import feed_status
from app.facts.models import Fact
from app.facts.projections import visible_facts


@dataclass(frozen=True)
class Unknown:
    type: str
    key: str | None
    reason: str
    as_of: date | None = None

    def __str__(self) -> str:
        return "UNKNOWN"


# Which feeds can supply each fact type. An empty tuple means no source is connected.
FACT_SOURCES: dict[str, tuple[str, ...]] = {
    "appointment": (),
    "medication": ("pharmacy", "documents"),
    "diagnosis": ("claims", "documents"),
    "event": ("claims", "adt", "documents", "cm_platform"),
    "lab": ("labs",),
    "contact_point": ("cm_platform", "eligibility", "pharmacy"),
    "sdoh": ("sdoh",),
    "coverage": ("eligibility", "um"),
    "care_gap": ("care_gaps",),
    "consent": ("cm_platform",),
    "service": ("medicaid",),
    "preference": ("cm_platform",),
    "risk": ("risk",),
}
NOT_CONNECTED = {"appointment": "practice not connected"}


def unknown_reason(
    session: Session, fact_type: str, key: str | None, clock: Clock
) -> tuple[str, date | None]:
    feeds = FACT_SOURCES.get(fact_type, ())
    if not feeds:
        return NOT_CONNECTED.get(fact_type, f"no {fact_type} source connected"), None
    statuses = {s.feed: s for s in feed_status(session, clock)}
    from_claims = fact_type == "diagnosis" or (key or "").startswith("claim:")
    claims_as_of = statuses["claims"].data_as_of
    if from_claims and claims_as_of:
        return f"claims loaded through {claims_as_of.isoformat()}", claims_as_of
    loaded = [statuses[f] for f in feeds if statuses[f].last_good_load_at is not None]
    if not loaded:
        return f"no {', '.join(feeds)} data received", None
    as_of = max((s.data_as_of for s in loaded if s.data_as_of), default=None)
    return (
        f"not in {', '.join(feeds)} data" + (f" as of {as_of.isoformat()}" if as_of else "")
    ), as_of


def get_fact_or_unknown(
    session: Session, member_id: str, fact_type: str, key: str | None, *, clock: Clock
) -> Fact | Unknown:
    """Latest visible Fact of this type (and key), or an UNKNOWN that says why."""
    if not FACT_SOURCES.get(fact_type, ()):  # nothing could have supplied it
        reason, as_of = unknown_reason(session, fact_type, key, clock)
        return Unknown(fact_type, key, reason, as_of)
    today = clock.now().astimezone(PLAN_TZ).date()
    matches = [
        f
        for f in visible_facts(session, member_id)
        if f.type == fact_type
        and (key is None or f.key == key)
        and (f.event_date is None or f.event_date <= today)
    ]
    if matches:
        return max(matches, key=lambda f: (f.event_date or date.min, f.id))
    reason, as_of = unknown_reason(session, fact_type, key, clock)
    return Unknown(fact_type, key, reason, as_of)
