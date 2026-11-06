"""Read clinical evidence out of a MemberSnapshot (Facts only; Part 2 records are excluded)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.clock import PLAN_TZ, Clock
from app.facts.models import Fact
from app.facts.snapshot import MemberSnapshot
from app.signals.calendar import timezone_for_state


def d(value: Any) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def num(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def plain(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def today(clock: Clock) -> date:
    return clock.now().astimezone(PLAN_TZ).date()


def facts(snapshot: MemberSnapshot, fact_type: str, key_prefix: str | None = None) -> list[Fact]:
    return [
        v.fact
        for v in snapshot.facts
        if not v.masked
        and v.fact.type == fact_type
        and (key_prefix is None or v.fact.key.startswith(key_prefix))
    ]


def member_tz(snapshot: MemberSnapshot) -> str:
    coverage = facts(snapshot, "coverage", "plan:")
    state = coverage[-1].value.get("state") if coverage else None
    return timezone_for_state(state)


def condition_groups(snapshot: MemberSnapshot) -> dict[str, list[Fact]]:
    groups: dict[str, list[Fact]] = {}
    for fact in facts(snapshot, "diagnosis"):
        group = fact.value.get("condition_group")
        if group:
            groups.setdefault(group, []).append(fact)
    return groups


def open_care_gaps(snapshot: MemberSnapshot, measure: str | None = None) -> list[Fact]:
    return [
        f
        for f in facts(snapshot, "care_gap")
        if f.value.get("status") == "open" and (measure is None or f.key == measure)
    ]


@dataclass
class Episode:
    """A discharge or ED visit on one local date, with every fact that evidences it."""

    day: date
    facts: list[Fact] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)

    @property
    def key_fact(self) -> Fact:
        return max(self.facts, key=lambda f: (f.event_date or date.min, f.id))


def _merge(episodes: list[Episode], day: date, fact: Fact, source: str, tolerance: int = 1) -> None:
    for episode in episodes:
        if abs((episode.day - day).days) <= tolerance:
            episode.facts.append(fact)
            episode.sources.add(source)
            return
    episodes.append(Episode(day, [fact], {source}))


def inpatient_discharges(snapshot: MemberSnapshot) -> list[Episode]:
    """ADT inpatient discharges, plus TRC care-gap anchors (the plan's own discharge record) and
    discharges a nurse recorded by hand while the ADT feed was down."""
    episodes: list[Episode] = []
    for fact in facts(snapshot, "event", "adt:discharge"):
        when = dt(fact.value.get("discharge_at"))
        if fact.value.get("patient_class") == "I" and when:
            _merge(episodes, when.astimezone(PLAN_TZ).date(), fact, "adt")
    for fact in facts(snapshot, "event", "manual:discharge"):
        when = dt(fact.value.get("discharge_at"))
        if when:
            _merge(episodes, when.astimezone(PLAN_TZ).date(), fact, "nurse")
    for fact in facts(snapshot, "care_gap"):
        if fact.key == "TRC" and fact.value.get("anchor_date"):
            _merge(episodes, d(fact.value["anchor_date"]) or date.min, fact, "care_gap")
    return sorted(episodes, key=lambda e: e.day)


def psych_discharges(snapshot: MemberSnapshot) -> list[Episode]:
    """Discharges the plan flags for FUH (follow-up after hospitalisation for mental illness)."""
    episodes: list[Episode] = []
    for gap in facts(snapshot, "care_gap"):
        if gap.key == "FUH" and gap.value.get("anchor_date"):
            _merge(episodes, d(gap.value["anchor_date"]) or date.min, gap, "care_gap")
    for episode in episodes:  # attach the ADT discharge for the same stay
        for fact in facts(snapshot, "event", "adt:discharge"):
            when = dt(fact.value.get("discharge_at"))
            if when and abs((when.astimezone(PLAN_TZ).date() - episode.day).days) <= 1:
                episode.facts.append(fact)
                episode.sources.add("adt")
    return sorted(episodes, key=lambda e: e.day)


def ed_visits(snapshot: MemberSnapshot) -> list[Episode]:
    """ED visits from ADT (one per visit number) and claims, de-duplicated by date (+/- 1 day)."""
    episodes: list[Episode] = []
    by_visit: dict[str, list[Fact]] = {}
    for fact in facts(snapshot, "event", "adt:"):
        if fact.value.get("patient_class") == "E":
            by_visit.setdefault(fact.value.get("visit_number") or str(fact.id), []).append(fact)
    for visit_facts in by_visit.values():
        starts = [dt(f.value.get("admit_at")) for f in visit_facts]
        first = min((s for s in starts if s), default=None)
        day = (
            first.astimezone(PLAN_TZ).date()
            if first
            else min(f.event_date or date.max for f in visit_facts)
        )
        for fact in visit_facts:
            _merge(episodes, day, fact, "adt")
    for fact in facts(snapshot, "event", "claim:ed"):
        if fact.event_date:
            _merge(episodes, fact.event_date, fact, "claims")
    return sorted(episodes, key=lambda e: e.day)


def successful_contact_since(snapshot: MemberSnapshot, since: date) -> bool:
    return any(
        f.value.get("outcome") == "answered" and (f.event_date or date.min) >= since
        for f in facts(snapshot, "event", "outreach:")
    )


def fills(snapshot: MemberSnapshot, drug_class: str | None = None) -> list[Fact]:
    return [
        f
        for f in facts(snapshot, "medication")
        if f.value.get("source_kind") == "pharmacy_claim"
        and (drug_class is None or f.value.get("drug_class") == drug_class)
    ]


def dispensed(items: list[Fact]) -> list[Fact]:
    return [f for f in items if f.value.get("dispensed")]


def latest(items: list[Fact]) -> Fact | None:
    return max(items, key=lambda f: (f.event_date or date.min, f.id), default=None)
