from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import ClockDep, DbSession, require_role
from app.datalayer_mock.identity.models import Member
from app.encounters import service
from app.encounters.models import Encounter, EncounterField, Task
from app.workbench.access import check_member_access
from app.workbench.models import User
from app.writeback import service as writeback
from app.writeback.client import CmClient, CmUnavailableError, get_cm_client

router = APIRouter(tags=["encounters"])
CaseManager = Annotated[User, Depends(require_role("cm"))]
Cm = Annotated[CmClient, Depends(get_cm_client)]
Staff = Annotated[User, Depends(require_role("cm", "supervisor", "call_agent"))]
CALLBACK_NUMBER = "555-0101"  # synthetic plan callback line


class LadderOut(BaseModel):
    number: str
    channel: str
    owner: str
    owner_name: str | None
    confidence: Decimal
    best_window: str | None
    best_start: str | None
    authorised: bool
    callable: bool
    reason: str


class CallPlanOut(BaseModel):
    member_id: str
    member_name: str
    language: str | None
    proxy_language: str | None
    summary: str
    ladder: list[LadderOut]
    opening_script: str
    identity_step: str
    voicemail_script: str
    resumable_encounter_id: int | None


class StartRequest(BaseModel):
    member_id: str
    number: str
    channel: Literal["phone", "sms", "video"] = "phone"
    interpreter_booked: bool = False


class SmsRequest(BaseModel):  # deliberately no override field
    number: str
    text: str = Field(min_length=1, max_length=320)


class FieldOut(BaseModel):
    field_id: str
    group: str
    label: str
    risk: str
    status: str
    reason: str | None
    prefill: Any | None
    source_fact_ids: list[int]
    source_as_of: date | None
    answer: Any | None
    confirmed: bool
    method: str | None
    time_on_field_ms: int | None


class TaskOut(BaseModel):
    id: int
    member_id: str
    kind: str
    title: str
    due_date: date
    status: str
    signal_rule_id: str | None
    signal_input_fact_ids: list[int]
    resolved_at: datetime | None = None
    resolution: str | None = None
    resolution_fact_ids: list[int] = []


class EncounterOut(BaseModel):
    id: int
    member_id: str
    cm_id: str
    channel: str
    number_used: str
    started_at: datetime
    ended_at: datetime | None
    outcome: str | None
    status: str
    identity_verified: bool
    transcription_consent: bool
    notes: str | None
    autosave: dict[str, Any] | None
    counts: dict[str, int]
    fields: list[FieldOut]
    tasks: list[TaskOut]


class ConfirmRequest(BaseModel):
    answer: Any | None = None
    time_on_field_ms: int | None = Field(default=None, ge=0)


class BulkRequest(BaseModel):
    field_ids: list[str] = Field(min_length=1)


class WrapRequest(BaseModel):
    outcome: (
        Literal["connected", "voicemail", "no_answer", "disconnected", "wrong_person", "declined"]
        | None
    ) = None
    notes: str | None = None


class AutosaveRequest(BaseModel):
    payload: dict[str, Any]


class NoteRequest(BaseModel):
    note: str = Field(min_length=3)


class InboundRequest(BaseModel):
    from_number: str


class SaveRequest(BaseModel):
    acknowledged_version: int | None = None


class ResolutionRequest(BaseModel):
    resolution: str = Field(min_length=3)
    decided_by_prescriber: bool = False


def _field_out(f: EncounterField) -> FieldOut:
    return FieldOut(
        field_id=f.field_id,
        group=f.group,
        label=f.label,
        risk=f.risk,
        status=f.status,
        reason=f.reason,
        prefill=f.prefill,
        source_fact_ids=f.source_fact_ids,
        source_as_of=f.source_as_of,
        answer=f.answer,
        confirmed=f.confirmed,
        method=f.method,
        time_on_field_ms=f.time_on_field_ms,
    )


def _task_out(t: Task) -> TaskOut:
    return TaskOut(
        id=t.id,
        member_id=t.member_id,
        kind=t.kind,
        title=t.title,
        due_date=t.due_date,
        status=t.status,
        signal_rule_id=t.signal_rule_id,
        signal_input_fact_ids=t.signal_input_fact_ids,
        resolved_at=t.resolved_at,
        resolution=t.resolution,
        resolution_fact_ids=t.resolution_fact_ids or [],
    )


def _out(session: DbSession, encounter: Encounter) -> EncounterOut:
    items = service.fields(session, encounter.id)
    counts = {
        s: sum(1 for f in items if f.status == s)
        for s in ("prefilled_fresh", "prefilled_stale", "live_only")
    }
    tasks = [
        t for t in service.tasks_for(session, encounter.member_id) if t.encounter_id == encounter.id
    ]
    return EncounterOut(
        id=encounter.id,
        member_id=encounter.member_id,
        cm_id=encounter.cm_id,
        channel=encounter.channel,
        number_used=encounter.number_used,
        started_at=encounter.started_at,
        ended_at=encounter.ended_at,
        outcome=encounter.outcome,
        status=encounter.status,
        identity_verified=encounter.identity_verified,
        transcription_consent=encounter.transcription_consent,
        notes=encounter.notes,
        autosave=encounter.autosave,
        counts=counts,
        fields=[_field_out(f) for f in items],
        tasks=[_task_out(t) for t in tasks],
    )


@router.get("/members/{member_id}/call-plan")
def call_plan(
    member_id: str, session: DbSession, clock: ClockDep, user: CaseManager
) -> CallPlanOut:
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no member {member_id}")
    check_member_access(session, user, member_id, supervisor_ok=False)
    ladder = service.channel_ladder(session, member_id, clock)
    preferred, proxy = service._member_languages(session, member_id)
    resumable = service.resumable(session, user, member_id)
    return CallPlanOut(
        member_id=member_id,
        member_name=f"{member.first_name} {member.last_name}",
        language=preferred,
        proxy_language=proxy,
        summary=service.ladder_summary(ladder),
        ladder=[LadderOut(**vars(e)) for e in ladder],
        opening_script=f"Hello, this is {user.name} from Evergreen Health Plan. "
        f"May I speak with {member.first_name}?",
        identity_step="Before anything else, please tell me your full name and date of birth.",
        voicemail_script=f"Hello, this is {user.name} from Evergreen Health Plan calling for "
        f"{member.first_name}. Please call us back at {CALLBACK_NUMBER}. "
        "Thank you.",
        resumable_encounter_id=resumable.id if resumable else None,
    )


@router.post("/encounters", status_code=status.HTTP_201_CREATED)
def start(
    body: StartRequest, session: DbSession, clock: ClockDep, user: CaseManager, cm: Cm
) -> EncounterOut:
    """Place a simulated call. Guards: authorised number, interpreter, pending duplicate."""
    check_member_access(session, user, body.member_id, supervisor_ok=False)
    encounter = service.start_encounter(
        session, user, body.member_id, body.number, body.channel, body.interpreter_booked, clock
    )
    try:  # remember the CM record version the nurse is working from
        encounter.cm_base_version = cm.record_version(body.member_id)
    except CmUnavailableError:
        encounter.cm_base_version = None  # unknown: the save will ask the nurse to review
    session.commit()
    return _out(session, encounter)


@router.post("/members/{member_id}/sms", status_code=status.HTTP_202_ACCEPTED)
def send_sms(
    member_id: str, body: SmsRequest, session: DbSession, clock: ClockDep, user: CaseManager
) -> dict[str, str]:
    """Hard-blocked (403, audited) without TCPA consent for that exact number. No override."""
    check_member_access(session, user, member_id, supervisor_ok=False)
    service.send_sms(session, user, member_id, body.number, clock)
    session.commit()
    return {"status": "queued (simulated)"}


@router.get("/encounters/{encounter_id}")
def get_encounter(encounter_id: int, session: DbSession, user: CaseManager) -> EncounterOut:
    return _out(session, service.get_encounter(session, encounter_id, user))


@router.post("/encounters/{encounter_id}/verify-identity")
def verify_identity(
    encounter_id: int, session: DbSession, clock: ClockDep, user: CaseManager
) -> EncounterOut:
    encounter = service.verify_identity(session, user, encounter_id, clock)
    session.commit()
    return _out(session, encounter)


@router.post("/encounters/{encounter_id}/autosave")
def autosave(
    encounter_id: int, body: AutosaveRequest, session: DbSession, clock: ClockDep, user: CaseManager
) -> dict[str, Any]:
    encounter = service.autosave(session, user, encounter_id, body.payload, clock)
    session.commit()
    return {"saved_at": encounter.autosaved_at}


@router.post("/encounters/{encounter_id}/fields/bulk-confirm")
def bulk_confirm(
    encounter_id: int, body: BulkRequest, session: DbSession, clock: ClockDep, user: CaseManager
) -> list[FieldOut]:
    """Low-risk prefilled_fresh fields only; any medication/allergy/dose field gives 422."""
    items = service.bulk_confirm(session, user, encounter_id, body.field_ids, clock)
    session.commit()
    return [_field_out(f) for f in items]


@router.post("/encounters/{encounter_id}/fields/{field_id}/confirm")
def confirm_field(
    encounter_id: int,
    field_id: str,
    body: ConfirmRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> FieldOut:
    field = service.confirm_field(
        session, user, encounter_id, field_id, body.answer, body.time_on_field_ms, clock
    )
    session.commit()
    return _field_out(field)


@router.post("/encounters/{encounter_id}/wrap-up")
def wrap_up(
    encounter_id: int, body: WrapRequest, session: DbSession, clock: ClockDep, user: CaseManager
) -> EncounterOut:
    """Creates tasks from the member's signals; those signals become handled; re-ranks."""
    encounter, _ = service.wrap_up(session, user, encounter_id, body.outcome, body.notes, clock)
    session.commit()
    return _out(session, encounter)


@router.post("/encounters/{encounter_id}/save")
def save(
    encounter_id: int,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
    cm: Cm,
    body: SaveRequest | None = None,
) -> EncounterOut:
    """Write back to the CM platform: saved -> syncing -> synced, idempotent, never overwriting.

    409 with both versions when the CM record changed since the call was opened.
    """
    try:
        encounter = writeback.save(
            session, user, encounter_id, clock, cm, body.acknowledged_version if body else None
        )
    except writeback.WritebackConflictError as conflict:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "reason": "the CM record changed since you opened it; review both versions",
                "ours": conflict.ours,
                "theirs": conflict.theirs,
                "base_version": conflict.base_version,
                "current_version": conflict.current_version,
            },
        ) from conflict
    session.commit()
    return _out(session, encounter)


@router.post("/encounters/{encounter_id}/conflicts/{conflict_id}/resolution")
def record_resolution(
    encounter_id: int,
    conflict_id: int,
    body: ResolutionRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> dict[str, Any]:
    """Record a person's decision; the conflict closes when the save syncs to the record."""
    encounter = writeback.record_resolution(
        session, user, encounter_id, conflict_id, body.resolution, body.decided_by_prescriber, clock
    )
    session.commit()
    return {"pending_resolutions": encounter.conflict_resolutions}


@router.post("/admin/writeback/run")
def run_writeback(
    session: DbSession,
    clock: ClockDep,
    cm: Cm,
    user: Annotated[User, Depends(require_role("supervisor"))],
) -> dict[str, list[int]]:
    """Retry due write-backs now (the worker does this every 30 s)."""
    summary = writeback.sync_due(session, clock, cm)
    session.commit()
    return {
        "synced": summary.synced,
        "retrying": summary.retrying,
        "conflicts": summary.conflicts,
        "alerted": summary.alerted,
    }


@router.post("/encounters/{encounter_id}/crisis")
def crisis(encounter_id: int, session: DbSession, clock: ClockDep, user: Staff) -> dict[str, Any]:
    """Never waits for documentation: flags, notifies the supervisor, returns transfer steps."""
    result = service.crisis(session, user, encounter_id, clock)
    session.commit()
    return result


@router.post("/encounters/{encounter_id}/flag-concern")
def flag_concern(
    encounter_id: int, body: NoteRequest, session: DbSession, clock: ClockDep, user: CaseManager
) -> dict[str, bool]:
    service.flag_concern(session, user, encounter_id, body.note, clock)
    session.commit()
    return {"flagged": True}


@router.post("/inbound-call")
def inbound_call(
    body: InboundRequest, session: DbSession, clock: ClockDep, user: Staff
) -> dict[str, Any]:
    return service.inbound_call(session, body.from_number, clock)


@router.get("/members/search")
def search(
    session: DbSession, user: Staff, last_name: Annotated[str, Query(min_length=2)], dob: date
) -> list[dict[str, str]]:
    return [
        {"member_id": m.member_id, "name": f"{m.first_name} {m.last_name}"}
        for m in service.search_members(session, last_name, dob)
    ]


@router.get("/members/{member_id}/tasks")
def member_tasks(
    member_id: str,
    session: DbSession,
    user: Annotated[User, Depends(require_role("cm", "supervisor"))],
) -> list[TaskOut]:
    check_member_access(session, user, member_id)
    return [_task_out(t) for t in service.tasks_for(session, member_id)]


@router.get("/tasks")
def my_tasks(
    session: DbSession, user: Annotated[User, Depends(require_role("cm", "supervisor"))]
) -> list[TaskOut]:
    """Tasks created from calls: a CM sees their own, a supervisor sees all."""
    query = select(Task).order_by(Task.due_date, Task.id)
    if user.role == "cm":
        query = query.where(Task.assigned_to == user.username)
    return [_task_out(t) for t in session.scalars(query)]
