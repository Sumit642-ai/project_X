from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api import schemas
from app.api.deps import ClockDep, DbSession, require_role
from app.datalayer_mock.identity.models import Member
from app.scoring.models import MemberScore
from app.workbench import actions
from app.workbench.access import check_member_access
from app.workbench.audit import audit
from app.workbench.models import User
from app.workbench.views import build_360

router = APIRouter(prefix="/members", tags=["members"])
CaseWorker = Annotated[User, Depends(require_role("cm", "supervisor"))]
CaseManager = Annotated[User, Depends(require_role("cm"))]


def _member(session: DbSession, member_id: str) -> Member:
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no member {member_id}")
    return member


@router.get("/{member_id}/score/explain")
def explain_score(member_id: str, session: DbSession, user: CaseWorker) -> schemas.ExplainOut:
    _member(session, member_id)
    check_member_access(session, user, member_id)
    row = session.scalars(
        select(MemberScore)
        .where(MemberScore.member_id == member_id)
        .order_by(MemberScore.run_day.desc())
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no score yet")
    return schemas.ExplainOut(
        member_id=member_id,
        explanation=row.explanation,
        tier=row.tier,
        r=row.r,
        r_source=row.r_source,
        verify=row.verify,
        u=row.u,
        u_deadline=row.u_deadline,
        u_clinical=row.u_clinical,
        hours_to_deadline=row.hours_to_deadline,
        deadline_source=row.deadline_source,
        m=row.m,
        m_lever=row.m_lever,
        a=row.a,
        a_contact=row.a_contact,
        input_fact_ids=row.input_fact_ids,
    )


@router.get("/{member_id}/360")
def member_360(
    member_id: str, session: DbSession, clock: ClockDep, user: CaseWorker
) -> schemas.Member360:
    """Everything about one member. Part 2 records are masked; every view is audited."""
    _member(session, member_id)
    check_member_access(session, user, member_id)
    view = build_360(session, member_id, clock)
    audit(
        session,
        clock,
        actor=user.username,
        action="view_360",
        object_type="member",
        object_id=member_id,
        member_id=member_id,
    )
    session.commit()
    return view


@router.post("/{member_id}/links/{link_id}/{decision}")
def decide_link(
    member_id: str,
    link_id: int,
    decision: Literal["confirm", "reject"],
    session: DbSession,
    clock: ClockDep,
    user: CaseWorker,
) -> schemas.LinkDecisionOut:
    _member(session, member_id)
    check_member_access(session, user, member_id)
    link = actions.decide_link(session, user, member_id, link_id, decision, clock)
    session.commit()
    return schemas.LinkDecisionOut(
        link_id=link.id, status=link.status, decided_by=link.decided_by, decided_at=link.decided_at
    )


@router.post("/{member_id}/discharges", status_code=status.HTTP_201_CREATED)
def record_discharge(
    member_id: str,
    body: schemas.DischargeRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> dict[str, int | str]:
    """Record a discharge by hand (used when the ADT feed is down). Re-scores the member."""
    _member(session, member_id)
    check_member_access(session, user, member_id)
    fact = actions.record_discharge(
        session, user, member_id, body.facility, body.discharge_at, body.note, clock
    )
    session.commit()
    return {"fact_id": fact.id, "status": fact.status}


@router.post("/{member_id}/part2/reveal")
def reveal_part2(
    member_id: str,
    body: schemas.ReasonRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> schemas.Part2RevealOut:
    """Assigned case manager only, and only while a valid Part 2 consent exists."""
    _member(session, member_id)
    check_member_access(session, user, member_id, supervisor_ok=False)
    try:
        event, consent, notes = actions.reveal_part2(session, user, member_id, body.reason, clock)
    except actions.ActionError:
        session.commit()  # keep the audit row for the refused attempt
        raise
    session.commit()
    return schemas.Part2RevealOut(
        member_id=member_id,
        consent_id=consent.id,
        audit_event_id=event.id,
        notes=[
            schemas.Part2NoteOut(
                fact_id=n.id,
                service_date=n.event_date,
                program=n.value.get("program_name"),
                note_type=n.value.get("note_type"),
                counselor=n.value.get("counselor"),
                note_text=n.value.get("note_text"),
            )
            for n in notes
        ],
        redisclosure_notice=actions.REDISCLOSURE_NOTICE,
    )


@router.post("/{member_id}/not-for-me")
def not_for_me(
    member_id: str,
    body: schemas.ReasonRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> schemas.AssignmentOut:
    """Hand a member back to the supervisor's unassigned list (audited override)."""
    _member(session, member_id)
    assignment = actions.not_for_me(session, user, member_id, body.reason, clock)
    session.commit()
    return schemas.AssignmentOut.model_validate(assignment)


@router.post("/{member_id}/snooze")
def snooze(
    member_id: str,
    body: schemas.SnoozeRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> schemas.SnoozeOut:
    """Hide a member from your queue until a return date (at most 30 days)."""
    _member(session, member_id)
    check_member_access(session, user, member_id, supervisor_ok=False)
    record = actions.snooze(session, user, member_id, body.reason, body.until, clock)
    session.commit()
    return schemas.SnoozeOut.model_validate(record)


@router.post("/{member_id}/not-now")
def not_now(
    member_id: str,
    body: schemas.NotNowRequest,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
) -> schemas.AckOut:
    """Decline the suggested next best action for now (audited)."""
    _member(session, member_id)
    check_member_access(session, user, member_id, supervisor_ok=False)
    event = actions.not_now(session, user, member_id, body.reason, body.rule_id, clock)
    session.commit()
    return schemas.AckOut(audit_event_id=event.id)
