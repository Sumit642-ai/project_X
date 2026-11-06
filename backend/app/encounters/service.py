"""Encounter workflow: simulated dialer, channel ladder, guards, assessment, wrap-up, hand-offs.

No real calls or messages are ever placed. Outcomes come from data/seed/dial_script.json.
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.core.config import REPO_ROOT
from app.datalayer_mock.identity.models import NEEDS_REVIEW, Member, MemberLink
from app.encounters.models import Encounter, EncounterField, Notification, SignalHandle, Task
from app.encounters.template import evaluate_template
from app.facts.builders import FactSpec, value_hash
from app.facts.contacts import DISCONNECTED_CAP
from app.facts.models import ContactPoint, Fact
from app.facts.snapshot import member_snapshot
from app.scoring.service import rescore_member
from app.signals.calendar import default_calendar
from app.signals.models import SignalRecord
from app.workbench.access import active_assignment
from app.workbench.actions import ActionError
from app.workbench.audit import audit
from app.workbench.models import User

CRISIS_LINES = [
    {"name": "988 Suicide & Crisis Lifeline", "number": "988"},
    {"name": "Evergreen behavioral health crisis line (synthetic)", "number": "555-0199"},
]
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# --- simulated dialer -------------------------------------------------------------------------


def dial_script(path: Path | None = None) -> dict[str, Any]:
    # The script is committed seed data (data/seed), independent of DATA_DIR.
    path = path or REPO_ROOT / "data" / "seed" / "dial_script.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def simulated_outcome(number: str, clock: Clock, script: dict[str, Any] | None = None) -> str:
    script = script or dial_script()
    entry = script.get("numbers", {}).get(number, {})
    weekday = WEEKDAYS[clock.now().astimezone(PLAN_TZ).weekday()]
    outcome: str = entry.get(weekday) or entry.get("default") or script.get("default", "no_answer")
    return outcome


# --- channel ladder ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LadderEntry:
    number: str
    channel: str  # phone | sms | video
    owner: str
    owner_name: str | None
    confidence: Decimal
    best_window: str | None
    best_start: str | None
    authorised: bool
    callable: bool
    reason: str


def _window_start(window: str | None) -> str | None:
    if not window:
        return None
    if match := re.search(r"(\d{1,2}):(\d{2})", window):
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    return "18:00" if "evening" in window.lower() else None


def _in_window(window: str | None, now: datetime) -> bool:
    if not window:
        return True
    times = re.findall(r"(\d{1,2}):(\d{2})", window)
    minutes = now.hour * 60 + now.minute
    if len(times) >= 2:
        start, end = (int(h) * 60 + int(m) for h, m in times[:2])
        return start <= minutes < end
    start_text = _window_start(window)
    if start_text:
        h, m = start_text.split(":")
        return minutes >= int(h) * 60 + int(m)
    return True


def channel_ladder(session: Session, member_id: str, clock: Clock) -> list[LadderEntry]:
    """Number + channel, ranked by contact confidence (past success, recency, source).

    SMS appears only with TCPA consent on that exact number; video only with a member opt-in
    (none on file yet). When now is outside a number's best window and SMS is allowed, the
    text comes first ("text first, then call at the best time").
    """
    now = clock.now().astimezone(PLAN_TZ)
    contacts = list(
        session.scalars(select(ContactPoint).where(ContactPoint.member_id == member_id))
    )
    entries: list[tuple[tuple[Any, ...], LadderEntry]] = []
    for c in contacts:
        start = _window_start(c.best_window)
        reachable = policy.contact_status(c)[0]
        texting = policy.has_sms_consent(c) and reachable
        base: dict[str, Any] = dict(
            number=c.number,
            owner=c.owner,
            owner_name=c.owner_name,
            confidence=c.confidence,
            best_window=c.best_window,
            best_start=start,
            authorised=policy.is_authorised(c),
            callable=reachable,
        )
        outside = not _in_window(c.best_window, now)
        entries.append(
            (
                (not reachable, -c.confidence, 1 if outside and texting else 0),
                LadderEntry(
                    channel="phone",
                    reason="call" + (f" at {start}" if outside and start else ""),
                    **base,
                ),
            )
        )
        if texting:
            entries.append(
                (
                    (False, -c.confidence, 0 if outside else 2),
                    LadderEntry(channel="sms", reason="TCPA consent on file", **base),
                )
            )
    return [entry for _, entry in sorted(entries, key=lambda item: (item[0], item[1].number))]


def ladder_summary(ladder: list[LadderEntry]) -> str:
    callable_ = [e for e in ladder if e.callable]
    if not callable_:
        return "No callable contact: find a new number before calling"
    top = callable_[0]
    if top.channel == "sms":
        return (
            f"Text first, then call {top.best_start or 'later'}"
            if top.best_start
            else "Text first, then call"
        )
    if top.reason.startswith("call at"):
        return f"Call {top.number} at {top.best_start}"
    return f"Call {top.number} now"


# --- guards -----------------------------------------------------------------------------------


def _contact(session: Session, member_id: str, number: str) -> ContactPoint | None:
    return session.scalars(
        select(ContactPoint).where(
            ContactPoint.member_id == member_id, ContactPoint.number == number
        )
    ).first()


def _member_languages(session: Session, member_id: str) -> tuple[str | None, str | None]:
    pref = session.scalars(
        select(Fact).where(
            Fact.member_id == member_id, Fact.type == "preference", Fact.superseded_by.is_(None)
        )
    ).first()
    if pref is None:
        return None, None
    return pref.value.get("preferred_language"), pref.value.get("proxy_language")


def check_can_contact(
    session: Session,
    user: User,
    member_id: str,
    number: str,
    channel: str,
    interpreter_booked: bool,
    clock: Clock,
) -> ContactPoint:
    decision = policy.can_call(session, member_id, number, clock=clock)
    if not decision:
        raise ActionError(403, decision.reason)
    contact = _contact(session, member_id, number)
    assert contact is not None  # can_call found it
    sms = policy.can_sms(session, member_id, number, clock=clock) if channel == "sms" else None
    if sms is not None and not sms:
        # Hard block: there is deliberately no override parameter.
        audit(
            session,
            clock,
            actor=user.username,
            action="sms_blocked",
            object_type="contact",
            object_id=number,
            member_id=member_id,
            reason=sms.reason,
        )
        session.commit()
        raise ActionError(403, sms.reason)
    if channel == "video":
        raise ActionError(403, "video visits need a member opt-in; none on file")
    preferred, proxy = _member_languages(session, member_id)
    spoken = proxy if contact.owner != "self" and proxy else preferred
    if channel == "phone" and spoken and spoken != "en" and not interpreter_booked:
        raise ActionError(
            409,
            f"member speaks {spoken} and no interpreter is booked: "
            "reschedule with an interpreter or reroute to a "
            f"{spoken}-speaking case manager",
        )
    return contact


def check_no_pending_match(session: Session, member_id: str) -> None:
    pending = session.scalars(
        select(MemberLink).where(
            MemberLink.member_id == member_id, MemberLink.status == NEEDS_REVIEW
        )
    ).first()
    if pending is not None:
        raise ActionError(409, "confirm or reject the possible duplicate before charting")


# --- encounter lifecycle ----------------------------------------------------------------------


def workbench_fact(member_id: str, spec: FactSpec, now: datetime, status: str = "raw") -> Fact:
    return Fact(
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
        status=status,
        sensitivity="none",
        value_hash=value_hash(spec),
        created_at=now,
    )


def _record_outreach(session: Session, encounter: Encounter, outcome: str, clock: Clock) -> None:
    """Every attempt becomes an outreach Fact, so rules and the ladder see it."""
    now = clock.now()
    mapped = {"connected": "answered"}.get(outcome, outcome)
    spec = FactSpec(
        "event",
        f"outreach:{encounter.channel}",
        {
            "phone": encounter.number_used,
            "channel": encounter.channel,
            "attempted_at": now.isoformat(),
            "outcome": mapped,
            "cm_name": encounter.cm_id,
            "encounter_id": encounter.id,
            "source_kind": "encounter",
        },
        f"encounter:{encounter.id}:attempt",
        now.astimezone(PLAN_TZ).date(),
    )
    session.add(workbench_fact(encounter.member_id, spec, now))
    contact = _contact(session, encounter.member_id, encounter.number_used)
    if contact is not None:
        contact.last_outcome = (
            mapped
            if mapped in ("answered", "voicemail", "no_answer", "disconnected")
            else contact.last_outcome
        )
        if outcome == "disconnected":
            contact.confidence = min(contact.confidence, DISCONNECTED_CAP)
            contact.callable = False
        elif outcome == "connected":
            contact.last_verified = now.astimezone(PLAN_TZ).date()


def start_encounter(
    session: Session,
    user: User,
    member_id: str,
    number: str,
    channel: str,
    interpreter_booked: bool,
    clock: Clock,
) -> Encounter:
    check_can_contact(session, user, member_id, number, channel, interpreter_booked, clock)
    check_no_pending_match(session, member_id)
    if channel == "sms":
        raise ActionError(422, "SMS is a message, not an encounter: use the message endpoint")
    outcome = simulated_outcome(number, clock)
    encounter = Encounter(
        member_id=member_id,
        cm_id=user.username,
        channel=channel,
        number_used=number,
        started_at=clock.now(),
        status="open",
        outcome=outcome,
        interpreter_booked=interpreter_booked,
        autosave={},
    )
    session.add(encounter)
    session.flush()
    _record_outreach(session, encounter, outcome, clock)
    if outcome == "connected":
        materialise_template(session, encounter, clock)
    audit(
        session,
        clock,
        actor=user.username,
        action="encounter_started",
        object_type="encounter",
        object_id=encounter.id,
        member_id=member_id,
        detail={"number": number, "outcome": outcome},
    )
    session.flush()
    return encounter


def send_sms(session: Session, user: User, member_id: str, number: str, clock: Clock) -> None:
    check_can_contact(session, user, member_id, number, "sms", False, clock)
    audit(
        session,
        clock,
        actor=user.username,
        action="sms_sent_simulated",
        object_type="contact",
        object_id=number,
        member_id=member_id,
    )


def materialise_template(session: Session, encounter: Encounter, clock: Clock) -> None:
    snapshot = member_snapshot(session, encounter.member_id, clock=clock)
    for state in evaluate_template(snapshot, clock):
        session.add(
            EncounterField(
                encounter_id=encounter.id,
                field_id=state.definition.field_id,
                group=state.definition.group,
                label=state.definition.label,
                risk=state.definition.risk,
                status=state.status,
                reason=state.reason,
                prefill=state.prefill.value if state.prefill else None,
                source_fact_ids=[f.id for f in state.prefill.facts] if state.prefill else [],
                source_as_of=state.prefill.as_of if state.prefill else None,
            )
        )
    session.flush()


def fields(session: Session, encounter_id: int) -> list[EncounterField]:
    return list(
        session.scalars(
            select(EncounterField)
            .where(EncounterField.encounter_id == encounter_id)
            .order_by(EncounterField.id)
        )
    )


def open_encounter(session: Session, encounter_id: int, user: User) -> Encounter:
    encounter = session.get(Encounter, encounter_id)
    if encounter is None:
        raise ActionError(404, f"no encounter {encounter_id}")
    if encounter.cm_id != user.username:
        raise ActionError(403, "only the case manager on the call can chart it")
    return encounter


def get_encounter(session: Session, encounter_id: int, user: User) -> Encounter:
    return open_encounter(session, encounter_id, user)


def verify_identity(session: Session, user: User, encounter_id: int, clock: Clock) -> Encounter:
    encounter = open_encounter(session, encounter_id, user)
    encounter.identity_verified = True
    audit(
        session,
        clock,
        actor=user.username,
        action="identity_verified",
        object_type="encounter",
        object_id=encounter_id,
        member_id=encounter.member_id,
    )
    return encounter


def autosave(
    session: Session, user: User, encounter_id: int, payload: dict[str, Any], clock: Clock
) -> Encounter:
    encounter = open_encounter(session, encounter_id, user)
    if encounter.status not in ("open", "wrapped"):
        raise ActionError(409, f"encounter is {encounter.status}")
    encounter.autosave = payload
    encounter.autosaved_at = clock.now()
    if "notes" in payload:
        encounter.notes = payload["notes"]
    if "transcription_consent" in payload:
        encounter.transcription_consent = bool(payload["transcription_consent"])
    return encounter


def resumable(session: Session, user: User, member_id: str) -> Encounter | None:
    return session.scalars(
        select(Encounter)
        .where(
            Encounter.member_id == member_id,
            Encounter.cm_id == user.username,
            Encounter.status.in_(("open", "wrapped")),
        )
        .order_by(Encounter.id.desc())
    ).first()


def _require_identity(encounter: Encounter) -> None:
    if not encounter.identity_verified:
        raise ActionError(409, "verify the member's identity before any health detail")


def confirm_field(
    session: Session,
    user: User,
    encounter_id: int,
    field_id: str,
    answer: Any | None,
    time_on_field_ms: int | None,
    clock: Clock,
) -> EncounterField:
    encounter = open_encounter(session, encounter_id, user)
    _require_identity(encounter)
    field = session.scalars(
        select(EncounterField).where(
            EncounterField.encounter_id == encounter_id, EncounterField.field_id == field_id
        )
    ).first()
    if field is None:
        raise ActionError(404, f"no field {field_id}")
    if field.status != "prefilled_fresh" and answer is None:
        raise ActionError(422, f"{field_id} must be asked: give the member's answer")
    if field.risk == "high" and time_on_field_ms is None:
        raise ActionError(422, f"{field_id} is high-risk: time_on_field_ms is required")
    field.answer = answer if answer is not None else field.prefill
    field.confirmed, field.method = True, "single"
    field.confirmed_by, field.confirmed_at = user.username, clock.now()
    field.time_on_field_ms = time_on_field_ms
    return field


def bulk_confirm(
    session: Session, user: User, encounter_id: int, field_ids: list[str], clock: Clock
) -> list[EncounterField]:
    encounter = open_encounter(session, encounter_id, user)
    _require_identity(encounter)
    by_id = {f.field_id: f for f in fields(session, encounter_id)}
    unknown = [f for f in field_ids if f not in by_id]
    high = [f for f in field_ids if f in by_id and by_id[f].risk == "high"]
    not_fresh = [f for f in field_ids if f in by_id and by_id[f].status != "prefilled_fresh"]
    if unknown or high or not_fresh:
        parts = []
        if high:
            parts.append(f"high-risk fields must be confirmed one by one: {', '.join(high)}")
        if not_fresh:
            parts.append(f"not prefilled fresh, ask instead: {', '.join(not_fresh)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise ActionError(422, "; ".join(parts))
    now = clock.now()
    for field_id in field_ids:
        field = by_id[field_id]
        field.answer, field.confirmed, field.method = field.prefill, True, "bulk"
        field.confirmed_by, field.confirmed_at = user.username, now
    return [by_id[f] for f in field_ids]


# --- wrap-up: tasks and handled signals -------------------------------------------------------

TASK_RULES: dict[str, tuple[str, str, int]] = {
    # rule_id: (kind, title template, business days until due)
    "NO_CRITICAL_MED_ON_HAND": (
        "prescriber_message",
        "Message prescriber: confirm loop-diuretic dose and supply",
        1,
    ),
    "EXPECTED_REFILL_MISSING": (
        "prescriber_message",
        "Message prescriber about refill: {insight}",
        1,
    ),
    "DRUG_REJECTED_NO_REQUEST": (
        "coverage_request",
        "Track coverage request (prescriber files): {insight}",
        1,
    ),
    "HF_DISCHARGE": ("pcp_visit_ride", "Book PCP follow-up visit and ride", 5),
    "FMC_DUE": ("pcp_visit_ride", "Book follow-up visit within 7 days of ED visit, with ride", 2),
    "FUH_DUE": ("pcp_visit_ride", "Confirm behavioral health follow-up and ride", 2),
    "DISCHARGE_SUMMARY_MISSING": ("hie_requery", "Re-query HIE for the discharge summary", 1),
    "NONFORMULARY_NEVER_FILLED": (
        "prescriber_message",
        "Ask prescriber about the formulary alternative",
        2,
    ),
    "RESCUE_MED_GAP_AFTER_ED": ("prescriber_message", "Arrange rescue inhaler refill", 1),
    "LTSS_HOURS_CUT": ("appeal_support", "Support aide-hours appeal: {insight}", 3),
    "CAREGIVER_STRAIN": ("caregiver_support", "Refer caregiver for respite and support", 5),
    "PSYCH_DISCHARGE_NO_CONTACT": ("bh_follow_up", "Confirm behavioral health follow-up", 1),
}


def handled_keys(session: Session, member_id: str) -> set[tuple[str, tuple[int, ...]]]:
    return {
        (h.rule_id, tuple(sorted(h.input_fact_ids)))
        for h in session.scalars(select(SignalHandle).where(SignalHandle.member_id == member_id))
    }


def wrap_up(
    session: Session,
    user: User,
    encounter_id: int,
    outcome: str | None,
    notes: str | None,
    clock: Clock,
) -> tuple[Encounter, list[Task]]:
    encounter = open_encounter(session, encounter_id, user)
    if encounter.status != "open":
        raise ActionError(409, f"encounter is already {encounter.status}")
    if outcome:
        encounter.outcome = outcome
    if notes is not None:
        encounter.notes = notes
    encounter.ended_at = clock.now()
    encounter.status = "wrapped"
    tasks: list[Task] = []
    if encounter.outcome == "connected":
        _require_identity(encounter)
        tasks = _tasks_from_signals(session, user, encounter, clock)
    audit(
        session,
        clock,
        actor=user.username,
        action="encounter_wrapped",
        object_type="encounter",
        object_id=encounter.id,
        member_id=encounter.member_id,
        detail={"tasks": [t.id for t in tasks], "outcome": encounter.outcome},
    )
    rescore_member(session, encounter.member_id, clock)
    return encounter, tasks


def _tasks_from_signals(
    session: Session, user: User, encounter: Encounter, clock: Clock
) -> list[Task]:
    today = clock.now().astimezone(PLAN_TZ).date()
    calendar = default_calendar()
    already = handled_keys(session, encounter.member_id)
    run_day = session.scalar(
        select(SignalRecord.run_day)
        .where(SignalRecord.member_id == encounter.member_id)
        .order_by(SignalRecord.run_day.desc())
    )
    signals = list(
        session.scalars(
            select(SignalRecord)
            .where(SignalRecord.member_id == encounter.member_id, SignalRecord.run_day == run_day)
            .order_by(SignalRecord.id)
        )
    )
    tasks: list[Task] = []
    by_kind: dict[str, Task] = {}
    for signal in signals:
        rule = TASK_RULES.get(signal.rule_id)
        key = (signal.rule_id, tuple(sorted(signal.input_fact_ids)))
        if rule is None or key in already:
            continue
        kind, title, days = rule
        task = by_kind.get(kind) if kind == "prescriber_message" else None
        if task is None:
            due = (
                signal.due_at.astimezone(PLAN_TZ).date()
                if signal.due_at
                else calendar.add_business_days(today, days)
            )
            task = Task(
                member_id=encounter.member_id,
                encounter_id=encounter.id,
                kind=kind,
                title=title.format(insight=signal.insight_text),
                due_date=due,
                status="open",
                assigned_to=user.username,
                signal_rule_id=signal.rule_id,
                signal_input_fact_ids=list(signal.input_fact_ids),
                created_at=clock.now(),
            )
            session.add(task)
            session.flush()
            tasks.append(task)
            by_kind[kind] = task
        session.add(
            SignalHandle(
                member_id=encounter.member_id,
                rule_id=signal.rule_id,
                input_fact_ids=list(signal.input_fact_ids),
                task_id=task.id,
                handled_by=user.username,
                handled_at=clock.now(),
            )
        )
    session.flush()
    return tasks


# --- tasks resolved by new data ---------------------------------------------------------------

# Which new data can show a task's signal is answered, by rule. A fill answers a refill gap only
# for the same drug (same Fact key); a coverage decision answers a coverage request. Tasks from any
# other rule (visits, rides, summaries) are closed by a person, never by data.
RESOLVED_BY: dict[str, tuple[str, bool]] = {
    # rule_id: (fact type that can answer it, must the key match an input Fact's key?)
    "NO_CRITICAL_MED_ON_HAND": ("medication", True),
    "EXPECTED_REFILL_MISSING": ("medication", True),
    "RESCUE_MED_GAP_AFTER_ED": ("medication", True),
    "NONFORMULARY_NEVER_FILLED": ("medication", True),
    "DRUG_REJECTED_NO_REQUEST": ("coverage", False),
    "DME_AUTH_OVERDUE": ("coverage", False),
}


def _describe(fact: Fact) -> str:
    v = fact.value
    if fact.type == "medication":
        verb = "filled" if v.get("dispensed") else "rejected"
        return f"{v.get('product') or fact.key} {v.get('strength') or ''} {verb} {fact.event_date}"
    if fact.type == "coverage":
        return f"{v.get('item') or fact.key} {v.get('status') or ''} {v.get('decision_date') or ''}"
    return f"{fact.key} {fact.event_date}"


def resolve_tasks_by_data(session: Session, clock: Clock) -> list[Task]:
    """Close open tasks whose signals no longer fire after new data arrived.

    A task is resolved only when every signal it came from is in RESOLVED_BY, none of them fires
    today, and a relevant new Fact (loaded after the task was created) explains why. The
    resolution names those Facts.
    """
    now = clock.now()
    run_day = now.astimezone(PLAN_TZ).date()
    firing = {
        (r.member_id, r.rule_id)
        for r in session.execute(
            select(SignalRecord.member_id, SignalRecord.rule_id).where(
                SignalRecord.run_day == run_day
            )
        )
    }
    resolved = []
    for task in session.scalars(select(Task).where(Task.status == "open").order_by(Task.id)):
        handles = list(session.scalars(select(SignalHandle).where(SignalHandle.task_id == task.id)))
        rules = {h.rule_id for h in handles} or (
            {task.signal_rule_id} if task.signal_rule_id else set()
        )
        if not rules or not rules <= RESOLVED_BY.keys():
            continue  # closed by a person
        if any((task.member_id, rule) in firing for rule in rules):
            continue
        input_ids = {i for h in handles for i in h.input_fact_ids} | set(task.signal_input_fact_ids)
        input_keys = set(session.scalars(select(Fact.key).where(Fact.id.in_(input_ids))))
        evidence = []
        for fact in session.scalars(
            select(Fact)
            .where(
                Fact.member_id == task.member_id,
                Fact.loaded_at > task.created_at,
                Fact.superseded_by.is_(None),
                Fact.source_system != "cm_workbench",
            )
            .order_by(Fact.id.desc())
        ):
            if any(
                fact.type == RESOLVED_BY[rule][0]
                and (not RESOLVED_BY[rule][1] or fact.key in input_keys)
                for rule in rules
            ):
                evidence.append(fact)
        evidence = evidence[:5]
        if not evidence:
            continue  # the signal stopped for another reason (e.g. a deadline passed): keep open
        task.status, task.resolved_at = "done", now
        task.resolution_fact_ids = [f.id for f in evidence]
        task.resolution = "Resolved by data: " + "; ".join(
            " ".join(_describe(f).split()) for f in evidence[:2]
        )
        audit(
            session,
            clock,
            actor="system:data",
            action="task_resolved_by_data",
            object_type="task",
            object_id=task.id,
            member_id=task.member_id,
            detail={"rules": sorted(rules), "fact_ids": task.resolution_fact_ids},
        )
        resolved.append(task)
    session.flush()
    return resolved


# --- hand-offs --------------------------------------------------------------------------------


def inbound_call(session: Session, from_number: str, clock: Clock) -> dict[str, Any]:
    contact = session.scalars(
        select(ContactPoint)
        .where(ContactPoint.number == from_number)
        .order_by(ContactPoint.confidence.desc())
    ).first()
    if contact is None:
        return {
            "matched": False,
            "next_step": "search_by_name_and_dob",
            "search": "/members/search?last_name=&dob=",
            "message": "Number not on file. Ask for the caller's name and date of birth.",
        }
    member = session.get(Member, contact.member_id)
    assignment = active_assignment(session, contact.member_id)
    run_day = session.scalar(
        select(SignalRecord.run_day)
        .where(SignalRecord.member_id == contact.member_id)
        .order_by(SignalRecord.run_day.desc())
    )
    signals = list(
        session.scalars(
            select(SignalRecord).where(
                SignalRecord.member_id == contact.member_id, SignalRecord.run_day == run_day
            )
        )
    )
    order = {"red": 0, "amber": 1, "info": 2}
    top = sorted(signals, key=lambda s: (order[s.severity], s.id))[:2]
    last_attempt = session.scalars(
        select(Fact)
        .where(
            Fact.member_id == contact.member_id,
            Fact.type == "event",
            Fact.key.like("outreach:%"),
            Fact.superseded_by.is_(None),
        )
        .order_by(Fact.event_date.desc(), Fact.id.desc())
    ).first()
    first = member.first_name if member else "the member"
    reasons = "; ".join(s.insight_text for s in top) or "a routine check-in"
    attempted = (
        f" We last tried to reach them on {last_attempt.event_date}." if last_attempt else ""
    )
    return {
        "matched": True,
        "member_id": contact.member_id,
        "caller": {"number": from_number, "owner": contact.owner, "name": contact.owner_name},
        "route_to": assignment.cm_username if assignment else "supervisor",
        "why_we_called": f"We called {first} about: {reasons}.{attempted} "
        "Verify name and date of birth before sharing any health detail.",
    }


def search_members(session: Session, last_name: str, dob: date) -> list[Member]:
    return list(
        session.scalars(
            select(Member).where(Member.last_name.ilike(last_name.strip()), Member.dob == dob)
        )
    )


def _supervisors(session: Session) -> list[str]:
    return list(session.scalars(select(User.username).where(User.role == "supervisor")))


def crisis(session: Session, user: User, encounter_id: int, clock: Clock) -> dict[str, Any]:
    """Act first, document later: flag, notify, and return transfer steps immediately."""
    encounter = session.get(Encounter, encounter_id)
    if encounter is None:
        raise ActionError(404, f"no encounter {encounter_id}")
    encounter.crisis = True
    for supervisor in _supervisors(session):
        session.add(
            Notification(
                recipient=supervisor,
                kind="crisis",
                member_id=encounter.member_id,
                encounter_id=encounter.id,
                message=f"Crisis protocol started by {user.username} on a call "
                f"with {encounter.member_id}.",
                created_at=clock.now(),
            )
        )
    audit(
        session,
        clock,
        actor=user.username,
        action="crisis_protocol",
        object_type="encounter",
        object_id=encounter.id,
        member_id=encounter.member_id,
    )
    return {
        "encounter_id": encounter.id,
        "supervisor_notified": _supervisors(session),
        "instructions": [
            "Stay on the line. Do not end the call.",
            "If there is immediate danger, call 911.",
            "Warm-transfer: conference in the crisis line, introduce the member, stay until "
            "the counselor has them.",
            "Document after the member is safe.",
        ],
        "transfer_lines": CRISIS_LINES,
    }


def flag_concern(
    session: Session, user: User, encounter_id: int, note: str, clock: Clock
) -> Encounter:
    encounter = open_encounter(session, encounter_id, user)
    encounter.clinical_concern = True
    for supervisor in _supervisors(session):
        session.add(
            Notification(
                recipient=supervisor,
                kind="clinical_concern",
                member_id=encounter.member_id,
                encounter_id=encounter.id,
                message=note,
                created_at=clock.now(),
            )
        )
    audit(
        session,
        clock,
        actor=user.username,
        action="clinical_concern",
        object_type="encounter",
        object_id=encounter.id,
        member_id=encounter.member_id,
        reason=note,
    )
    return encounter


def tasks_for(session: Session, member_id: str) -> list[Task]:
    return list(
        session.scalars(
            select(Task).where(Task.member_id == member_id).order_by(Task.due_date, Task.id)
        )
    )
