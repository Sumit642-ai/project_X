"""Conflict detection. Opens Conflicts; never picks a winner and never resolves one.

Medications: each hospital document's medication list is compared with the member's pharmacy
fills around the document date (dispensed fills covering the date, allowing 30 days past
covered_through; rejected claims within 30 days count as "prescribed").
  - dose:     both list the ingredient, strengths differ
  - presence: one side lists the ingredient and the other does not
Diagnoses: different codes in the same condition group from different source systems
(e.g. CKD stage 3a in claims vs stage 4 in a discharge summary).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.facts.models import Conflict, ConflictFact, Fact
from app.facts.projections import visible_facts

WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class Finding:
    member_id: str
    fact_type: str
    key: str
    kind: str
    summary: str
    fact_ids: tuple[int, ...]


def _d(value: Any) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _pharmacy_around(fills: list[Fact], day: date) -> list[Fact]:
    found = []
    for fill in fills:
        fill_date = _d(fill.value.get("fill_date"))
        if fill_date is None:
            continue
        if fill.value.get("dispensed"):
            covered = _d(fill.value.get("covered_through")) or fill_date
            if fill_date <= day <= covered + WINDOW:
                found.append(fill)
        elif abs((fill_date - day).days) <= WINDOW.days:
            found.append(fill)
    return found


def medication_findings(facts: Iterable[Fact]) -> list[Finding]:
    by_member: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.type == "medication":
            by_member.setdefault(fact.member_id, []).append(fact)
    findings = []
    for member_id, meds in sorted(by_member.items()):
        fills = [m for m in meds if m.value.get("source_kind") == "pharmacy_claim"]
        documents: dict[str, list[Fact]] = {}
        for med in meds:
            if med.value.get("source_kind") == "hospital_document" and med.event_date:
                documents.setdefault(med.value["document_id"], []).append(med)
        for doc_id, listed in sorted(documents.items()):
            day = listed[0].event_date
            assert day is not None
            nearby = _pharmacy_around(fills, day)
            doc_keys = {m.key: m for m in listed}
            for key in sorted(doc_keys.keys() | {f.key for f in nearby}):
                doc_med = doc_keys.get(key)
                pharmacy = [f for f in nearby if f.key == key]
                dispensed = [f for f in pharmacy if f.value.get("dispensed")]
                if doc_med is None:
                    if dispensed:  # a rejected claim alone does not mean the member takes it
                        latest = max(dispensed, key=lambda f: f.value["fill_date"])
                        findings.append(
                            Finding(
                                member_id,
                                "medication",
                                key,
                                "presence",
                                f"{key}: pharmacy fill {latest.value['strength']} "
                                f"({latest.value['fill_date']}) not on {doc_id}",
                                (latest.id,),
                            )
                        )
                    continue
                if not pharmacy:
                    findings.append(
                        Finding(
                            member_id,
                            "medication",
                            key,
                            "presence",
                            f"{key}: {doc_med.value['strength']} on {doc_id}, no pharmacy record",
                            (doc_med.id,),
                        )
                    )
                    continue
                latest = max(dispensed or pharmacy, key=lambda f: f.value["fill_date"])
                if (latest.value.get("strength") or "") != (doc_med.value.get("strength") or ""):
                    findings.append(
                        Finding(
                            member_id,
                            "medication",
                            key,
                            "dose",
                            f"{key}: pharmacy {latest.value['strength']} "
                            f"(filled {latest.value['fill_date']}) vs {doc_med.value['facility']} "
                            f"{doc_med.value['strength']} ({doc_id})",
                            (latest.id, doc_med.id),
                        )
                    )
    return findings


def diagnosis_findings(facts: Iterable[Fact]) -> list[Finding]:
    groups: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        group = fact.value.get("condition_group") if fact.type == "diagnosis" else None
        if group and fact.value.get("mapped"):
            groups.setdefault((fact.member_id, group), []).append(fact)
    findings = []
    for (member_id, group), items in sorted(groups.items()):
        codes_by_system: dict[str, set[str]] = {}
        for item in items:
            codes_by_system.setdefault(item.source_system, set()).add(item.key)
        all_codes = set().union(*codes_by_system.values())
        if len(codes_by_system) < 2 or len(all_codes) < 2:
            continue
        # Disagreement only if some system's codes differ from another's.
        systems = sorted(codes_by_system)
        if all(codes_by_system[s] == codes_by_system[systems[0]] for s in systems):
            continue
        detail = "; ".join(f"{s}: {', '.join(sorted(codes_by_system[s]))}" for s in systems)
        findings.append(
            Finding(
                member_id,
                "diagnosis",
                group,
                "code",
                f"{group} coded differently by source ({detail})",
                tuple(sorted(i.id for i in items)),
            )
        )
    return findings


def detect_conflicts(session: Session, clock: Clock) -> list[Conflict]:
    """Open a Conflict for every new finding. Existing conflicts are left exactly as they are."""
    facts = visible_facts(session)
    existing = list(session.scalars(select(Conflict)))
    fact_sets: dict[int, set[int]] = {}
    for link in session.scalars(select(ConflictFact)):
        fact_sets.setdefault(link.conflict_id, set()).add(link.fact_id)
    opened = []
    for finding in medication_findings(facts) + diagnosis_findings(facts):
        same = [
            c
            for c in existing
            if (c.member_id, c.fact_type, c.key, c.kind)
            == (finding.member_id, finding.fact_type, finding.key, finding.kind)
        ]
        if any(c.status != "resolved" for c in same):
            continue  # already open or with the prescriber
        if any(fact_sets.get(c.id) == set(finding.fact_ids) for c in same):
            continue  # a human already resolved exactly this disagreement
        conflict = Conflict(
            member_id=finding.member_id,
            fact_type=finding.fact_type,
            key=finding.key,
            kind=finding.kind,
            summary=finding.summary,
            detected_at=clock.now(),
            status="open",
        )
        session.add(conflict)
        session.flush()
        session.add_all(ConflictFact(conflict_id=conflict.id, fact_id=f) for f in finding.fact_ids)
        existing.append(conflict)
        fact_sets[conflict.id] = set(finding.fact_ids)
        opened.append(conflict)
    session.flush()
    return opened


def conflict_fact_ids(session: Session, conflict_id: int) -> list[int]:
    return sorted(
        session.scalars(select(ConflictFact.fact_id).where(ConflictFact.conflict_id == conflict_id))
    )


class ConflictDecisionError(ValueError):
    pass


def _human(user: str) -> None:
    if not user or user.startswith("system:"):
        raise ConflictDecisionError("conflicts are resolved by people, not by the system")


def send_to_prescriber(session: Session, conflict_id: int, user: str, *, clock: Clock) -> Conflict:
    _human(user)
    conflict = session.get(Conflict, conflict_id)
    if conflict is None or conflict.status != "open":
        raise ConflictDecisionError(f"conflict {conflict_id} is not open")
    conflict.status = "sent_to_prescriber"
    conflict.resolution = {"sent_by": user, "sent_at": clock.now().isoformat()}
    session.flush()
    return conflict


def resolve_conflict(
    session: Session, conflict_id: int, user: str, resolution: dict[str, Any], *, clock: Clock
) -> Conflict:
    """Record a human decision. Source Facts are left untouched."""
    _human(user)
    conflict = session.get(Conflict, conflict_id)
    if conflict is None or conflict.status == "resolved":
        raise ConflictDecisionError(f"conflict {conflict_id} cannot be resolved")
    conflict.status = "resolved"
    conflict.resolution = {**(conflict.resolution or {}), **resolution}
    conflict.resolved_by, conflict.resolved_at = user, clock.now()
    session.flush()
    return conflict
