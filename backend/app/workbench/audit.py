from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.workbench.models import AuditEvent


def audit(
    session: Session,
    clock: Clock,
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: str | int,
    member_id: str | None = None,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        member_id=member_id,
        reason=reason,
        detail=detail,
        at=clock.now(),
    )
    session.add(event)
    session.flush()
    return event
