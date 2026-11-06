"""Workbench actions. Each one checks its preconditions and writes an audit row."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity import confirm_link, reject_link
from app.datalayer_mock.identity.models import MemberLink
from app.facts import refresh_facts
from app.facts.builders import FactSpec, value_hash
from app.facts.conflicts import send_to_prescriber
from app.facts.models import Conflict, ConflictFact, ConsentRecord, DocumentRecord, Fact
from app.scoring.service import rescore_member
from app.workbench.access import active_assignment
from app.workbench.audit import audit
from app.workbench.models import Assignment, AuditEvent, Snooze, User

REDISCLOSURE_NOTICE = (
    "42 CFR Part 2: this record is protected by federal confidentiality rules. "
    "Further disclosure is prohibited unless expressly permitted by written consent."
)


class ActionError(ValueError):
    """A request the rules do not allow; carries the HTTP status to return."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


# --- Part 2 -----------------------------------------------------------------------------------


def reveal_part2(
    session: Session, user: User, member_id: str, reason: str, clock: Clock
) -> tuple[AuditEvent, ConsentRecord, list[Fact]]:
    decision = policy.can_reveal_part2(session, member_id, user, clock=clock)
    if not decision:
        why = decision.reason
        audit(
            session,
            clock,
            actor=user.username,
            action="part2_reveal_denied",
            object_type="member",
            object_id=member_id,
            member_id=member_id,
            reason=reason,
            detail={"why": why},
        )
        raise ActionError(403, why)
    notes = policy.revealable_facts(session, member_id)
    valid = session.get(ConsentRecord, decision.consent_id)
    assert valid is not None
    event = audit(
        session,
        clock,
        actor=user.username,
        action="part2_reveal",
        object_type="member",
        object_id=member_id,
        member_id=member_id,
        reason=reason,
        detail={"fact_ids": [n.id for n in notes], "consent_id": valid.id},
    )
    return event, valid, notes


# --- identity links ---------------------------------------------------------------------------


def decide_link(
    session: Session, user: User, member_id: str, link_id: int, decision: str, clock: Clock
) -> MemberLink:
    link = session.get(MemberLink, link_id)
    if link is None or link.member_id != member_id:
        raise ActionError(404, f"link {link_id} is not a candidate for {member_id}")
    try:
        if decision == "confirm":
            link = confirm_link(session, link_id, user.username, clock=clock)
        else:
            link = reject_link(session, link_id, user.username, clock=clock)
    except ValueError as exc:
        raise ActionError(409, str(exc)) from exc
    audit(
        session,
        clock,
        actor=user.username,
        action=f"link_{decision}ed",
        object_type="member_link",
        object_id=link_id,
        member_id=member_id,
        detail={
            "source": f"{link.source_system}:{link.source_record_id}",
            "confidence": str(link.confidence),
        },
    )
    if decision == "confirm":
        refresh_facts(session, clock)  # the linked records' Facts and conflicts appear now
        rescore_member(session, member_id, clock)
    return link


# --- conflicts --------------------------------------------------------------------------------


def report_from_member(
    session: Session, user: User, conflict: Conflict, value: str, clock: Clock
) -> Fact:
    """Record what the member says. The conflict stays open: a report is not a resolution."""
    now = clock.now()
    count = len(
        list(
            session.scalars(
                select(Fact).where(
                    Fact.source_system == "cm_workbench",
                    Fact.source_record_id.like(f"conflict:{conflict.id}:report:%"),
                )
            )
        )
    )
    spec = FactSpec(
        conflict.fact_type,
        conflict.key,
        {
            "reported": value,
            "conflict_id": conflict.id,
            "reported_by": user.username,
            "source_kind": "member_report",
        },
        f"conflict:{conflict.id}:report:{count + 1}",
        now.astimezone(PLAN_TZ).date(),
        confidence=Decimal("1.000"),
    )
    fact = Fact(
        member_id=conflict.member_id,
        link_id=None,
        type=spec.type,
        key=spec.key,
        value=spec.value,
        source_system="cm_workbench",
        source_record_id=spec.source_record_id,
        load_id=None,
        source_row=None,
        event_date=spec.event_date,
        loaded_at=now,
        confidence=spec.confidence,
        status="member_reported",
        sensitivity="none",
        value_hash=value_hash(spec),
        created_at=now,
    )
    session.add(fact)
    session.flush()
    session.add(ConflictFact(conflict_id=conflict.id, fact_id=fact.id))
    audit(
        session,
        clock,
        actor=user.username,
        action="member_report",
        object_type="conflict",
        object_id=conflict.id,
        member_id=conflict.member_id,
        detail={"fact_id": fact.id},
    )
    return fact


def record_discharge(
    session: Session,
    user: User,
    member_id: str,
    facility: str,
    discharge_at: datetime,
    note: str | None,
    clock: Clock,
) -> Fact:
    """A discharge the nurse learned of while the ADT feed was down. Stored as a
    member-reported Fact (never as ADT), so transition rules can fire on it."""
    if discharge_at.tzinfo is None:
        raise ActionError(422, "discharge_at needs a time zone")
    now = clock.now()
    if discharge_at > now:
        raise ActionError(422, "a discharge cannot be in the future")
    count = len(
        list(
            session.scalars(
                select(Fact.id).where(Fact.member_id == member_id, Fact.key == "manual:discharge")
            )
        )
    )
    spec = FactSpec(
        "event",
        "manual:discharge",
        {
            "facility": facility,
            "discharge_at": discharge_at.isoformat(),
            "patient_class": "I",
            "note": note,
            "reported_by": user.username,
            "source_kind": "nurse_entry_adt_down",
        },
        f"manual-discharge:{member_id}:{count + 1}",
        discharge_at.astimezone(PLAN_TZ).date(),
        confidence=Decimal("0.700"),
    )
    fact = Fact(
        member_id=member_id,
        link_id=None,
        type=spec.type,
        key=spec.key,
        value=spec.value,
        source_system="cm_workbench",
        source_record_id=spec.source_record_id,
        load_id=None,
        source_row=None,
        event_date=spec.event_date,
        loaded_at=now,
        confidence=spec.confidence,
        status="member_reported",
        sensitivity="none",
        value_hash=value_hash(spec),
        created_at=now,
    )
    session.add(fact)
    session.flush()
    audit(
        session,
        clock,
        actor=user.username,
        action="discharge_recorded",
        object_type="fact",
        object_id=fact.id,
        member_id=member_id,
        detail={"facility": facility, "discharge_at": discharge_at.isoformat()},
    )
    rescore_member(session, member_id, clock)
    return fact


def conflict_to_prescriber(
    session: Session, user: User, conflict: Conflict, clock: Clock
) -> Conflict:
    try:
        send_to_prescriber(session, conflict.id, user.username, clock=clock)
    except ValueError as exc:
        raise ActionError(409, str(exc)) from exc
    audit(
        session,
        clock,
        actor=user.username,
        action="sent_to_prescriber",
        object_type="conflict",
        object_id=conflict.id,
        member_id=conflict.member_id,
    )
    return conflict


# --- assignment -------------------------------------------------------------------------------


def not_for_me(
    session: Session, user: User, member_id: str, reason: str, clock: Clock
) -> Assignment:
    assignment = active_assignment(session, member_id)
    if assignment is None or assignment.cm_username != user.username:
        raise ActionError(403, f"{member_id} is not assigned to {user.username}")
    assignment.status, assignment.ended_at, assignment.reason = "declined", clock.now(), reason
    audit(
        session,
        clock,
        actor=user.username,
        action="override_not_for_me",
        object_type="assignment",
        object_id=assignment.id,
        member_id=member_id,
        reason=reason,
    )
    session.flush()
    return assignment


def _member_state_and_languages(session: Session, member_id: str) -> tuple[str | None, set[str]]:
    facts = list(
        session.scalars(
            select(Fact).where(
                Fact.member_id == member_id,
                Fact.superseded_by.is_(None),
                Fact.type.in_(("coverage", "preference")),
            )
        )
    )
    state = next(
        (f.value.get("state") for f in facts if f.type == "coverage" and f.key.startswith("plan:")),
        None,
    )
    languages: set[str] = set()
    for fact in facts:
        if fact.type == "preference":
            languages.update(
                v
                for v in (fact.value.get("preferred_language"), fact.value.get("proxy_language"))
                if v
            )
        elif fact.type == "coverage" and fact.value.get("language"):
            languages.add(fact.value["language"])
    return state, languages


def reassign(
    session: Session,
    supervisor: User,
    member_id: str,
    to_cm: str,
    override_reason: str | None,
    clock: Clock,
) -> Assignment:
    target = session.get(User, to_cm)
    if target is None or target.role != "cm":
        raise ActionError(422, f"{to_cm} is not a case manager")
    state, languages = _member_state_and_languages(session, member_id)
    if state is None:
        raise ActionError(422, f"{member_id}: member state is UNKNOWN; cannot check licensure")
    if state not in target.licensed_states:
        raise ActionError(
            422,
            f"{to_cm} is not licensed in {state} (licensed: "
            f"{', '.join(target.licensed_states) or 'none'})",
        )
    shared = languages & set(target.languages)
    if languages and not shared and not override_reason:
        raise ActionError(
            422,
            f"{to_cm} does not speak the member's language "
            f"({', '.join(sorted(languages))}); give override_reason to proceed",
        )
    now = clock.now()
    current = active_assignment(session, member_id)
    if current is not None:
        current.status, current.ended_at = "reassigned", now
    assignment = Assignment(
        member_id=member_id,
        cm_username=to_cm,
        status="active",
        assigned_by=supervisor.username,
        assigned_at=now,
        reason=override_reason or "reassigned by supervisor",
    )
    session.add(assignment)
    session.flush()
    detail: dict[str, Any] = {
        "from": current.cm_username if current else None,
        "to": to_cm,
        "state": state,
        "languages": sorted(languages),
    }
    audit(
        session,
        clock,
        actor=supervisor.username,
        action="reassignment",
        object_type="assignment",
        object_id=assignment.id,
        member_id=member_id,
        reason=override_reason,
        detail=detail,
    )
    if languages and not shared:
        audit(
            session,
            clock,
            actor=supervisor.username,
            action="override_language",
            object_type="assignment",
            object_id=assignment.id,
            member_id=member_id,
            reason=override_reason,
            detail=detail,
        )
    return assignment


# --- documents --------------------------------------------------------------------------------


def requery_document(
    session: Session, user: User, document: DocumentRecord, clock: Clock
) -> DocumentRecord:
    if document.status == "received":
        raise ActionError(409, "document already received")
    now = clock.now()
    count = len(
        list(
            session.scalars(
                select(Fact).where(
                    Fact.source_system == "cm_workbench",
                    Fact.source_record_id.like(f"document:{document.id}:requery:%"),
                )
            )
        )
    )
    spec = FactSpec(
        "event",
        f"document_request:{document.type}",
        {
            "document_type": document.type,
            "facility": document.facility,
            "requested_at": now.isoformat(),
            "status": "not_received",
            "requested_by": user.username,
            "source_kind": "requery",
        },
        f"document:{document.id}:requery:{count + 1}",
        now.astimezone(PLAN_TZ).date(),
    )
    session.add(
        Fact(
            member_id=document.member_id,
            link_id=None,
            type=spec.type,
            key=spec.key,
            value=spec.value,
            source_system="cm_workbench",
            source_record_id=spec.source_record_id,
            load_id=None,
            source_row=None,
            event_date=spec.event_date,
            loaded_at=now,
            confidence=Decimal("1.000"),
            status="raw",
            sensitivity="none",
            value_hash=value_hash(spec),
            created_at=now,
        )
    )
    document.requested_at = now.astimezone(UTC)
    document.evidence = [*document.evidence, {"requery_at": now.isoformat(), "by": user.username}]
    audit(
        session,
        clock,
        actor=user.username,
        action="document_requery",
        object_type="document",
        object_id=document.id,
        member_id=document.member_id,
    )
    session.flush()
    return document


# --- queue hygiene ----------------------------------------------------------------------------


def snooze(
    session: Session, user: User, member_id: str, reason: str, until: date, clock: Clock
) -> Snooze:
    today = clock.now().astimezone(PLAN_TZ).date()
    if until <= today:
        raise ActionError(422, "return date must be after today")
    if until > today + timedelta(days=30):
        raise ActionError(422, "snooze for at most 30 days")
    record = Snooze(
        member_id=member_id,
        cm_username=user.username,
        until=until,
        reason=reason,
        created_at=clock.now(),
    )
    session.add(record)
    audit(
        session,
        clock,
        actor=user.username,
        action="override_snooze",
        object_type="member",
        object_id=member_id,
        member_id=member_id,
        reason=reason,
        detail={"until": until.isoformat()},
    )
    return record


def not_now(
    session: Session, user: User, member_id: str, reason: str, rule_id: str | None, clock: Clock
) -> AuditEvent:
    """Decline the suggested next best action for now. Recorded, never silent."""
    return audit(
        session,
        clock,
        actor=user.username,
        action="override_not_now",
        object_type="member",
        object_id=member_id,
        member_id=member_id,
        reason=reason,
        detail={"rule_id": rule_id},
    )
