from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import schemas
from app.api.deps import ClockDep, CurrentUser, DbSession, require_role
from app.facts.models import DocumentRecord
from app.workbench import actions
from app.workbench.access import check_member_access
from app.workbench.feeds import stream_statuses
from app.workbench.models import User

router = APIRouter(tags=["documents", "feeds"])


@router.post("/documents/{document_id}/requery", status_code=status.HTTP_202_ACCEPTED)
def requery(
    document_id: int,
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("cm", "supervisor"))],
) -> schemas.DocumentOut:
    """Ask the HIE again for a document that has not arrived."""
    document = session.get(DocumentRecord, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no document {document_id}")
    check_member_access(session, user, document.member_id)
    actions.requery_document(session, user, document, clock)
    session.commit()
    return schemas.DocumentOut(
        id=document.id,
        type=document.type,
        facility=document.facility,
        status=document.status,
        requested_at=document.requested_at,
        received_at=document.received_at,
    )


@router.get("/feeds/status")
def feeds_status(
    session: DbSession, clock: ClockDep, user: CurrentUser
) -> list[schemas.FeedStatusOut]:
    return [
        schemas.FeedStatusOut(
            feed=s.feed,
            stream=s.stream,
            last_good_load_at=s.last_good_load_at,
            age_hours=s.age_hours,
            data_as_of=s.data_as_of,
            stale=s.stale,
            reason=s.reason,
        )
        for s in stream_statuses(session, clock)
    ]
