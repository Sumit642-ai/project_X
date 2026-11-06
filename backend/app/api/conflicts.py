from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import schemas
from app.api.deps import ClockDep, DbSession, require_role
from app.facts.conflicts import conflict_fact_ids
from app.facts.models import Conflict
from app.workbench import actions
from app.workbench.access import check_member_access
from app.workbench.models import User

router = APIRouter(prefix="/conflicts", tags=["conflicts"])


def _conflict(session: DbSession, conflict_id: int, user: User) -> Conflict:
    conflict = session.get(Conflict, conflict_id)
    if conflict is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no conflict {conflict_id}")
    check_member_access(session, user, conflict.member_id)
    return conflict


def _out(session: DbSession, conflict: Conflict) -> schemas.ConflictOut:
    return schemas.ConflictOut(
        id=conflict.id,
        fact_type=conflict.fact_type,
        key=conflict.key,
        kind=conflict.kind,
        summary=conflict.summary,
        status=conflict.status,
        fact_ids=conflict_fact_ids(session, conflict.id),
        detected_at=conflict.detected_at,
    )


@router.post("/{conflict_id}/member-reports", status_code=status.HTTP_201_CREATED)
def member_report(
    conflict_id: int,
    body: schemas.MemberReportRequest,
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("cm"))],
) -> schemas.FactCreatedOut:
    """What the member says they take. Stored as a member_reported Fact; never resolves."""
    conflict = _conflict(session, conflict_id, user)
    fact = actions.report_from_member(session, user, conflict, body.value, clock)
    session.commit()
    return schemas.FactCreatedOut(
        fact_id=fact.id, conflict_id=conflict.id, conflict_status=conflict.status
    )


@router.post("/{conflict_id}/send-to-prescriber")
def to_prescriber(
    conflict_id: int,
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("cm", "supervisor"))],
) -> schemas.ConflictOut:
    conflict = _conflict(session, conflict_id, user)
    actions.conflict_to_prescriber(session, user, conflict, clock)
    session.commit()
    return _out(session, conflict)
