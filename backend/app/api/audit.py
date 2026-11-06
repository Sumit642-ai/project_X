import csv
import io
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import ClockDep, DbSession, require_role
from app.consent import policy
from app.datalayer_mock.identity.models import Member
from app.encounters import service as encounters
from app.facts.models import ContactPoint, Fact
from app.workbench.access import check_member_access
from app.workbench.models import AuditEvent, User

router = APIRouter(tags=["audit", "members"])
CSV_COLUMNS = ("id", "at", "actor", "action", "object_type", "object_id", "member_id", "reason")


class AuditOut(BaseModel):
    id: int
    at: datetime
    actor: str
    action: str
    object_type: str
    object_id: str
    member_id: str | None
    reason: str | None
    detail: dict[str, Any] | None


@router.get("/audit", response_model=None)
def audit_log(
    session: DbSession,
    user: Annotated[User, Depends(require_role("supervisor"))],
    member_id: str | None = None,
    format: Annotated[Literal["json", "csv"], Query()] = "json",
) -> list[AuditOut] | Response:
    """Append-only audit trail (supervisors only). format=csv downloads it."""
    query = select(AuditEvent).order_by(AuditEvent.id)
    if member_id:
        query = query.where(AuditEvent.member_id == member_id)
    rows = list(session.scalars(query))
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.id,
                    row.at.isoformat(),
                    row.actor,
                    row.action,
                    row.object_type,
                    row.object_id,
                    row.member_id or "",
                    row.reason or "",
                ]
            )
        name = f"audit-{member_id or 'all'}.csv"
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )
    return [
        AuditOut(
            id=r.id,
            at=r.at,
            actor=r.actor,
            action=r.action,
            object_type=r.object_type,
            object_id=r.object_id,
            member_id=r.member_id,
            reason=r.reason,
            detail=r.detail,
        )
        for r in rows
    ]


class ContactCardContact(BaseModel):
    number: str
    owner: str
    owner_name: str | None
    best_window: str | None
    callable: bool
    not_callable_reason: str | None


class ContactCard(BaseModel):
    """Minimum necessary for a call agent: identity, reach ladder, why we called. No clinical."""

    member_id: str
    name: str
    dob: str
    contacts: list[ContactCardContact]
    why_we_called: str
    assigned_cm: str | None


@router.get("/members/{member_id}/contact-card")
def contact_card(
    member_id: str,
    session: DbSession,
    clock: ClockDep,
    user: Annotated[User, Depends(require_role("cm", "supervisor", "call_agent"))],
) -> ContactCard:
    member = session.get(Member, member_id)
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no member {member_id}")
    if user.role == "cm":
        check_member_access(session, user, member_id)
    contacts = list(
        session.scalars(
            select(ContactPoint)
            .where(ContactPoint.member_id == member_id)
            .order_by(ContactPoint.confidence.desc())
        )
    )
    entries = []
    for contact in contacts:
        reachable, why_not = policy.contact_status(contact)
        entries.append(
            ContactCardContact(
                number=contact.number,
                owner=contact.owner,
                owner_name=contact.owner_name,
                best_window=contact.best_window,
                callable=reachable,
                not_callable_reason=why_not,
            )
        )
    routing = encounters.inbound_call(session, contacts[0].number, clock) if contacts else {}
    return ContactCard(
        member_id=member_id,
        name=f"{member.first_name} {member.last_name}",
        dob=member.dob.isoformat(),
        contacts=entries,
        why_we_called=_non_clinical_reason(routing),
        assigned_cm=routing.get("route_to"),
    )


def _non_clinical_reason(routing: dict[str, Any]) -> str:
    # The CM-facing card names clinical signals; a call agent gets only the fact of a callback.
    if not routing.get("matched"):
        return "No recent outreach on record."
    return (
        "Your case manager tried to reach you and would like to talk. "
        "Verify name and date of birth, then transfer the caller."
    )


class MedicationOut(BaseModel):
    fact_id: int
    key: str
    source_system: str
    event_date: str | None
    value: dict[str, Any]


@router.get("/members/{member_id}/medications")
def medications(
    member_id: str,
    session: DbSession,
    user: Annotated[User, Depends(require_role("cm", "supervisor"))],
) -> list[MedicationOut]:
    """Clinical data: case managers and supervisors only (call agents get 403)."""
    check_member_access(session, user, member_id)
    facts = session.scalars(
        select(Fact)
        .where(Fact.member_id == member_id, Fact.type == "medication", Fact.superseded_by.is_(None))
        .order_by(Fact.event_date, Fact.id)
    )
    return [
        MedicationOut(
            fact_id=f.id,
            key=f.key,
            source_system=f.source_system,
            event_date=f.event_date.isoformat() if f.event_date else None,
            value=f.value,
        )
        for f in facts
        if not policy.is_masked(f)
    ]
