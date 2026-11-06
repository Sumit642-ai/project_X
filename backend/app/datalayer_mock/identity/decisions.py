"""Human decisions on links. Every decision writes a link_audit row.

Links are pointers from source records to golden members; no staging data is moved or
deleted. Unmerging therefore restores both histories: the member stops seeing the source's
records and the source record is unlinked again with all of its own records intact.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.datalayer_mock.identity.models import (
    AUTO_LINKED,
    CONFIRMED,
    LINKED_STATUSES,
    NEEDS_REVIEW,
    REJECTED,
    LinkAudit,
    MemberLink,
)


class LinkDecisionError(ValueError):
    pass


def _decide(
    session: Session,
    link_id: int,
    user: str,
    clock: Clock,
    *,
    action: str,
    allowed_from: tuple[str, ...],
    to_status: str,
    note: str | None = None,
) -> MemberLink:
    if not user or user.startswith("system:"):
        raise LinkDecisionError("link decisions need a named human user")
    link = session.get(MemberLink, link_id)
    if link is None:
        raise LinkDecisionError(f"no link {link_id}")
    if link.status not in allowed_from:
        raise LinkDecisionError(f"cannot {action} a link in status {link.status}")
    now = clock.now()
    session.add(
        LinkAudit(
            link_id=link.id,
            action=action,
            actor=user,
            at=now,
            from_status=link.status,
            to_status=to_status,
            note=note,
        )
    )
    link.status, link.decided_by, link.decided_at = to_status, user, now
    session.flush()
    return link


def confirm_link(session: Session, link_id: int, user: str, *, clock: Clock) -> MemberLink:
    return _decide(
        session,
        link_id,
        user,
        clock,
        action="confirmed",
        allowed_from=(NEEDS_REVIEW, AUTO_LINKED),
        to_status=CONFIRMED,
    )


def reject_link(session: Session, link_id: int, user: str, *, clock: Clock) -> MemberLink:
    """Reject a suggestion. The pair is never suggested again."""
    return _decide(
        session,
        link_id,
        user,
        clock,
        action="rejected",
        allowed_from=(NEEDS_REVIEW,),
        to_status=REJECTED,
    )


def unmerge(
    session: Session, member_id: str, link_id: int, user: str, *, clock: Clock
) -> MemberLink:
    link = session.get(MemberLink, link_id)
    if link is None or link.member_id != member_id:
        raise LinkDecisionError(f"link {link_id} does not attach to member {member_id}")
    return _decide(
        session,
        link_id,
        user,
        clock,
        action="unmerged",
        allowed_from=LINKED_STATUSES,
        to_status=REJECTED,
        note=f"detached {link.source_system}:{link.source_record_id}",
    )


@dataclass(frozen=True)
class HistoryEntry:
    source_system: str
    source_record_id: str
    link_id: int
    evidence: list[dict[str, Any]]


def member_history(session: Session, member_id: str) -> list[HistoryEntry]:
    """Source records currently attributed to a member (auto-linked or confirmed)."""
    links = session.scalars(
        select(MemberLink)
        .where(MemberLink.member_id == member_id, MemberLink.status.in_(LINKED_STATUSES))
        .order_by(MemberLink.id)
    )
    return [
        HistoryEntry(
            link.source_system,
            link.source_record_id,
            link.id,
            [e for e in link.evidence if e.get("role") != "golden record"],
        )
        for link in links
    ]


def is_linked(session: Session, source_system: str, source_record_id: str) -> bool:
    return (
        session.scalar(
            select(MemberLink.id).where(
                MemberLink.source_system == source_system,
                MemberLink.source_record_id == source_record_id,
                MemberLink.status.in_(LINKED_STATUSES),
            )
        )
        is not None
    )
