from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api import schemas
from app.api.deps import ClockDep, DbSession, require_role
from app.workbench import actions
from app.workbench.models import User
from app.workbench.views import build_queue

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("")
def get_queue(
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("cm", "supervisor"))],
    cm: Annotated[str, Query(description="me, a CM username, unassigned or all")] = "me",
) -> schemas.QueueOut:
    """Ranked members (tier, then score) with why-chips and the next best action."""
    if user.role == "cm":
        if cm not in ("me", user.username):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "case managers see their own queue")
        scope = user.username
    else:
        scope = "all" if cm == "me" else cm
    return build_queue(session, clock, scope=scope, user=user)


@router.post("/reassign")
def reassign(
    body: schemas.ReassignRequest,
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("supervisor"))],
) -> schemas.AssignmentOut:
    """Supervisor only. Refused with 422 when licensure or language does not fit."""
    assignment = actions.reassign(
        session, user, body.member_id, body.to_cm, body.override_reason, clock
    )
    session.commit()
    return schemas.AssignmentOut.model_validate(assignment)
