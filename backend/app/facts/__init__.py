"""Facts: append-only member facts with lineage, conflicts, freshness and member snapshots."""

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.facts.builders import BuildSummary, build_facts
from app.facts.conflicts import (
    ConflictDecisionError,
    detect_conflicts,
    resolve_conflict,
    send_to_prescriber,
)
from app.facts.contacts import contact_confidence
from app.facts.freshness import freshness
from app.facts.models import FactImmutableError
from app.facts.projections import rebuild_projections
from app.facts.snapshot import MemberSnapshot, member_snapshot
from app.facts.unknown import Unknown, get_fact_or_unknown


def refresh_facts(session: Session, clock: Clock) -> BuildSummary:
    """Build new Facts, rebuild the current-state tables, then look for conflicts."""
    summary = build_facts(session, clock)
    rebuild_projections(session, clock)
    detect_conflicts(session, clock)
    return summary


__all__ = [
    "BuildSummary",
    "ConflictDecisionError",
    "FactImmutableError",
    "MemberSnapshot",
    "Unknown",
    "build_facts",
    "contact_confidence",
    "detect_conflicts",
    "freshness",
    "get_fact_or_unknown",
    "member_snapshot",
    "rebuild_projections",
    "refresh_facts",
    "resolve_conflict",
    "send_to_prescriber",
]
