"""Write-back to the CM platform: idempotent, retried with backoff, never overwriting.

saved -> syncing -> synced. A save carries an idempotency key (encounter + payload hash), so a
retry can never create a duplicate. The write is conditional on the CM record version the nurse
opened; if it changed, the nurse gets both versions and nothing is written. Unreachable CM: the
save waits in the outbox and retries with exponential backoff for up to 2 hours, then alerts a
supervisor. Only a successful sync turns confirmed fields into cm_confirmed Facts (source Facts
are never deleted) and closes the conflicts the nurse resolved on the call.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_draft import service as ai_draft
from app.core.clock import PLAN_TZ, Clock
from app.encounters.models import Encounter, Notification, Task
from app.encounters.service import fields, open_encounter, workbench_fact
from app.facts.builders import FactSpec
from app.facts.conflicts import ConflictDecisionError, resolve_conflict
from app.facts.models import Conflict
from app.workbench.actions import ActionError
from app.workbench.audit import audit
from app.workbench.models import User
from app.writeback.client import CmClient, CmUnavailableError
from app.writeback.mapping import AiWriteForbiddenError, encode_section
from app.writeback.models import WritebackOutbox

FIRST_RETRY = timedelta(seconds=30)
MAX_RETRY_GAP = timedelta(minutes=30)
GIVE_UP_AFTER = timedelta(hours=2)


class WritebackConflictError(Exception):
    def __init__(
        self,
        ours: dict[str, Any],
        theirs: dict[str, Any] | None,
        base_version: int | None,
        current_version: int | None,
    ) -> None:
        super().__init__("CM record changed since it was opened")
        self.ours, self.theirs = ours, theirs
        self.base_version, self.current_version = base_version, current_version


# --- payload ----------------------------------------------------------------------------------


def build_payload(session: Session, encounter: Encounter) -> dict[str, Any]:
    """Raises AiWriteForbiddenError if AI-drafted text reached any field but the note body."""
    note_values: dict[str, Any] = {
        "notes": encounter.notes or "",
        "outcome": encounter.outcome,
        "number_used": encounter.number_used,
        "channel": encounter.channel,
        "started_at": encounter.started_at,
        "ended_at": encounter.ended_at,
        "cm_id": encounter.cm_id,
        "transcription_consent": encounter.transcription_consent,
        "identity_verified": encounter.identity_verified,
    }
    answers = {f.field_id: f.answer for f in fields(session, encounter.id) if f.confirmed}
    task_values = [
        {
            "kind": t.kind,
            "title": t.title,
            "due_date": t.due_date,
            "signal_rule_id": t.signal_rule_id,
        }
        for t in session.scalars(
            select(Task).where(Task.encounter_id == encounter.id).order_by(Task.id)
        )
    ]
    ai = ai_draft.ai_sourced_fields  # provenance: which values contain drafted sentences
    return {
        "note": encode_section("note", note_values, ai(session, encounter.id, note_values)),
        "assessment": encode_section("assessment", answers, ai(session, encounter.id, answers)),
        "tasks": [encode_section("task", t, ai(session, encounter.id, t)) for t in task_values],
    }


def idempotency_key(encounter_id: int, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"enc{encounter_id}-{digest[:16]}"


# --- save -------------------------------------------------------------------------------------


@dataclass
class SyncSummary:
    synced: list[int] = field(default_factory=list)
    retrying: list[int] = field(default_factory=list)
    conflicts: list[int] = field(default_factory=list)
    alerted: list[int] = field(default_factory=list)


def save(
    session: Session,
    user: User,
    encounter_id: int,
    clock: Clock,
    cm: CmClient,
    acknowledged_version: int | None = None,
) -> Encounter:
    encounter = open_encounter(session, encounter_id, user)
    if encounter.status in ("syncing", "synced"):
        return encounter  # saving again with the same call is a no-op, not a duplicate
    if encounter.status != "wrapped":
        raise ActionError(409, "wrap up the call before saving")
    items = fields(session, encounter_id)
    missing = [
        f.field_id
        for f in items
        if f.risk == "high" and f.status != "live_only" and not f.confirmed
    ]
    if missing:
        raise ActionError(422, f"confirm high-risk fields one by one first: {', '.join(missing)}")
    if acknowledged_version is not None:  # the nurse reviewed the newer CM version
        encounter.cm_base_version = acknowledged_version

    try:
        payload = build_payload(session, encounter)
    except AiWriteForbiddenError as exc:
        raise ActionError(422, str(exc)) from exc
    key = idempotency_key(encounter.id, payload)
    existing = session.scalars(
        select(WritebackOutbox).where(WritebackOutbox.idempotency_key == key)
    ).first()
    if existing is not None:
        return encounter
    ai_draft.record_guardrails(session, user, encounter, clock)

    now = clock.now()
    try:
        result = cm.write(encounter.member_id, key, payload, encounter.cm_base_version)
    except CmUnavailableError as exc:
        encounter.status = "saved"
        session.add(
            WritebackOutbox(
                encounter_id=encounter.id,
                member_id=encounter.member_id,
                idempotency_key=key,
                payload=payload,
                base_version=encounter.cm_base_version,
                status="pending",
                attempts=1,
                first_attempt_at=now,
                next_attempt_at=now + FIRST_RETRY,
                last_error=str(exc),
            )
        )
        encounter.status = "syncing"
        audit(
            session,
            clock,
            actor=user.username,
            action="writeback_queued",
            object_type="encounter",
            object_id=encounter.id,
            member_id=encounter.member_id,
            detail={"key": key, "error": str(exc)},
        )
        session.flush()
        return encounter
    if result.status == "conflict":
        # Nothing is persisted: the nurse decides with both versions in front of them.
        raise WritebackConflictError(
            payload, result.current, encounter.cm_base_version, result.version
        )
    outbox = WritebackOutbox(
        encounter_id=encounter.id,
        member_id=encounter.member_id,
        idempotency_key=key,
        payload=payload,
        base_version=encounter.cm_base_version,
        status="synced",
        attempts=1,
        first_attempt_at=now,
        next_attempt_at=now,
        synced_at=now,
        cm_version=result.version,
    )
    session.add(outbox)
    encounter.status = "saved"
    _apply_success(session, encounter, user.username, result.version, clock)
    return encounter


def _apply_success(
    session: Session, encounter: Encounter, actor: str, version: int | None, clock: Clock
) -> None:
    now = clock.now()
    for item in fields(session, encounter.id):
        if not item.confirmed:
            continue
        spec = FactSpec(
            "event",
            f"assessment:{item.field_id}",
            {
                "label": item.label,
                "answer": item.answer,
                "prefill_status": item.status,
                "source_fact_ids": item.source_fact_ids,
                "method": item.method,
                "encounter_id": encounter.id,
                "source_kind": "assessment",
            },
            f"encounter:{encounter.id}:{item.field_id}",
            now.astimezone(PLAN_TZ).date(),
        )
        session.add(workbench_fact(encounter.member_id, spec, now, status="cm_confirmed"))
    closed = []
    for resolution in encounter.conflict_resolutions or []:
        conflict = session.get(Conflict, resolution["conflict_id"])
        if conflict is None or conflict.status == "resolved":
            continue
        try:
            resolve_conflict(
                session,
                conflict.id,
                resolution["by"],
                {**resolution, "encounter_id": encounter.id},
                clock=clock,
            )
            closed.append(conflict.id)
        except ConflictDecisionError:
            continue
    encounter.status = "synced"
    audit(
        session,
        clock,
        actor=actor,
        action="encounter_synced",
        object_type="encounter",
        object_id=encounter.id,
        member_id=encounter.member_id,
        detail={"cm_version": version, "conflicts_closed": closed},
    )
    session.flush()


# --- retries ----------------------------------------------------------------------------------


def _backoff(attempts: int) -> timedelta:
    gap: timedelta = min(FIRST_RETRY * (2 ** max(attempts - 1, 0)), MAX_RETRY_GAP)
    return gap


def _supervisors(session: Session) -> list[str]:
    return list(session.scalars(select(User.username).where(User.role == "supervisor")))


def _alert(session: Session, outbox: WritebackOutbox, message: str, clock: Clock) -> None:
    for supervisor in _supervisors(session):
        session.add(
            Notification(
                recipient=supervisor,
                kind="writeback_failed",
                member_id=outbox.member_id,
                encounter_id=outbox.encounter_id,
                message=message,
                created_at=clock.now(),
            )
        )


def sync_due(session: Session, clock: Clock, cm: CmClient, *, now_all: bool = False) -> SyncSummary:
    """Retry every pending save whose next attempt is due (the worker calls this).

    now_all: retry every pending save immediately, e.g. when the platform is known to be back.
    """
    now: datetime = clock.now()
    summary = SyncSummary()
    query = select(WritebackOutbox).where(WritebackOutbox.status == "pending")
    if not now_all:
        query = query.where(WritebackOutbox.next_attempt_at <= now)
    due = session.scalars(query.order_by(WritebackOutbox.id))
    for outbox in list(due):
        encounter = session.get(Encounter, outbox.encounter_id)
        if encounter is None:
            continue
        outbox.attempts += 1
        try:
            result = cm.write(
                outbox.member_id, outbox.idempotency_key, outbox.payload, outbox.base_version
            )
        except CmUnavailableError as exc:
            outbox.last_error = str(exc)
            if now - outbox.first_attempt_at >= GIVE_UP_AFTER:
                outbox.status = "alerted"
                _alert(
                    session,
                    outbox,
                    f"Save for encounter {outbox.encounter_id} has not "
                    f"reached the CM platform for 2 hours: {exc}",
                    clock,
                )
                summary.alerted.append(outbox.id)
            else:
                outbox.next_attempt_at = now + _backoff(outbox.attempts)
                summary.retrying.append(outbox.id)
            continue
        if result.status == "conflict":
            outbox.status = "conflict"
            outbox.last_error = f"CM record now at version {result.version}"
            _alert(
                session,
                outbox,
                f"Save for encounter {outbox.encounter_id} conflicts with a "
                "newer CM record; the nurse must review both versions.",
                clock,
            )
            summary.conflicts.append(outbox.id)
            continue
        outbox.status, outbox.synced_at, outbox.cm_version = "synced", now, result.version
        _apply_success(session, encounter, "system:writeback", result.version, clock)
        summary.synced.append(outbox.id)
    session.flush()
    return summary


# --- conflict resolutions recorded during the call -------------------------------------------


def record_resolution(
    session: Session,
    user: User,
    encounter_id: int,
    conflict_id: int,
    resolution: str,
    decided_by_prescriber: bool,
    clock: Clock,
) -> Encounter:
    """A person's decision, applied (conflict closed) only once the save syncs."""
    encounter = open_encounter(session, encounter_id, user)
    conflict = session.get(Conflict, conflict_id)
    if conflict is None or conflict.member_id != encounter.member_id:
        raise ActionError(404, f"no conflict {conflict_id} for {encounter.member_id}")
    if conflict.fact_type == "medication" and not decided_by_prescriber:
        raise ActionError(
            422,
            "medication conflicts are decided by the prescriber; record their "
            "decision with decided_by_prescriber=true",
        )
    pending = [r for r in (encounter.conflict_resolutions or []) if r["conflict_id"] != conflict_id]
    encounter.conflict_resolutions = [
        *pending,
        {
            "conflict_id": conflict_id,
            "resolution": resolution,
            "by": user.username,
            "decided_by_prescriber": decided_by_prescriber,
            "at": clock.now().isoformat(),
        },
    ]
    audit(
        session,
        clock,
        actor=user.username,
        action="conflict_resolution_recorded",
        object_type="conflict",
        object_id=conflict_id,
        member_id=encounter.member_id,
        detail={"encounter_id": encounter_id, "resolution": resolution},
    )
    return encounter
