"""Current-state tables rebuilt from Facts (and HIE request staging): contact_points,
consents and documents. They are views of the Facts, so rebuilding them is safe."""

from datetime import date
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity.models import LINKED_STATUSES, MemberLink
from app.datalayer_mock.identity.sources import active_rows
from app.facts.contacts import contact_confidence
from app.facts.models import ConsentRecord, ContactPoint, DocumentRecord, Fact

OWNER = {
    "member": "self",
    "representative": "representative",
    "family": "third_party",
    "facility": "third_party",
}


def visible_facts(session: Session, member_id: str | None = None) -> list[Fact]:
    """Current Facts whose identity link is still auto-linked or confirmed.

    Facts entered in the workbench (e.g. member reports) carry no link and are always visible.
    """
    query = (
        select(Fact)
        .outerjoin(MemberLink, MemberLink.id == Fact.link_id)
        .where(
            Fact.superseded_by.is_(None),
            or_(Fact.link_id.is_(None), MemberLink.status.in_(LINKED_STATUSES)),
        )
        .order_by(Fact.id)
    )
    if member_id is not None:
        query = query.where(Fact.member_id == member_id)
    return list(session.scalars(query))


def _d(value: Any) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _rebuild_consents(session: Session, facts: list[Fact]) -> list[ConsentRecord]:
    records = []
    for fact in facts:
        if fact.type != "consent" or fact.source_system != "consents":
            continue  # eligibility representative fields stay as Facts (evidence) only
        v = fact.value
        valid_from = _d(v.get("granted_date")) or fact.event_date
        if valid_from is None:
            continue
        record = ConsentRecord(
            member_id=fact.member_id,
            type=v["consent_type"],
            scope=v.get("scope"),
            valid_from=valid_from,
            valid_to=_d(v.get("expires_date")),
            revoked_at=_d(v.get("revoked_date")),
            phone=v.get("phone"),
            program=v.get("program"),
            party_name=v.get("representative_name") or v.get("recipient"),
            relationship=v.get("relationship"),
            source=v.get("source"),
            fact_id=fact.id,
        )
        session.add(record)
        records.append(record)
    return records


def _rebuild_contacts(
    session: Session, facts: list[Fact], consents: list[ConsentRecord], today: date
) -> None:
    by_number: dict[tuple[str, str], list[Fact]] = {}
    for fact in facts:
        if fact.type == "contact_point" and fact.value.get("number"):
            by_number.setdefault((fact.member_id, fact.value["number"]), []).append(fact)
    attempts: dict[tuple[str, str], Fact] = {}
    for fact in facts:
        if fact.type == "event" and fact.value.get("source_kind") == "encounter":
            key = (fact.member_id, str(fact.value.get("phone")))
            if key not in attempts or fact.id > attempts[key].id:
                attempts[key] = fact
    sms = policy.sms_consented_numbers(consents, today)
    for (member_id, number), group in sorted(by_number.items()):
        # The CM platform ladder is the primary record; other sources only fill gaps.
        primary = next((f for f in group if f.value.get("from_cm_platform")), None)
        if primary is None:
            primary = max(group, key=lambda f: (f.event_date or date.min, f.id))
        v = primary.value
        last_verified = _d(v.get("last_verified")) or primary.event_date
        outcome = v.get("last_outcome")
        attempt = attempts.get((member_id, number))
        if attempt is not None:  # a workbench call is newer evidence than the CM platform export
            outcome = attempt.value.get("outcome")
            if outcome == "answered":
                last_verified = attempt.event_date
        score = contact_confidence(v.get("source"), last_verified, outcome, today)
        owner = OWNER.get(v.get("owner_type") or "member", "third_party")
        authorised = bool(v.get("authorized", owner == "self"))
        session.add(
            ContactPoint(
                member_id=member_id,
                number=number,
                owner=owner,
                owner_name=v.get("owner_name"),
                relationship=v.get("relationship"),
                source=v.get("source"),
                last_verified=last_verified,
                last_outcome=outcome,
                best_window=v.get("best_time"),
                confidence=score.confidence,
                confidence_factors=score.factors(),
                consent_sms=(member_id, number) in sms,
                authorised=authorised,
                callable=authorised and outcome != "disconnected",
                fact_ids=[f.id for f in group],
            )
        )


def _rebuild_documents(session: Session, facts: list[Fact]) -> None:
    linked = {
        (link.source_system, link.source_record_id): link.member_id
        for link in session.scalars(
            select(MemberLink).where(MemberLink.status.in_(LINKED_STATUSES))
        )
    }
    received = [f for f in facts if f.type == "event" and f.key.startswith("document:")]
    request_facts = {
        f.source_record_id: f.id
        for f in facts
        if f.type == "event" and f.key.startswith("document_request:")
    }
    matched: set[int] = set()
    for row in active_rows(session, "hie_requests"):
        member_id = linked.get(("hie_requests", row.member_id))
        if member_id is None:
            continue
        evidence: list[dict[str, Any]] = [
            {"stream": "hie_requests", "load_id": row.load_id, "source_row": row.source_row}
        ]
        if row.request_id in request_facts:
            evidence.append({"fact_id": request_facts[row.request_id], "role": "request"})
        doc = None
        if row.status == "received" and row.received_at is not None:
            day = row.received_at.astimezone(PLAN_TZ).date()
            doc = next(
                (
                    f
                    for f in received
                    if f.member_id == member_id
                    and f.id not in matched
                    and f.value.get("document_type") == row.document_type
                    and f.value.get("facility") == row.facility
                    and f.event_date is not None
                    and abs((f.event_date - day).days) <= 1
                ),
                None,
            )
        if doc is not None:
            matched.add(doc.id)
            evidence.append({"fact_id": doc.id})
        session.add(
            DocumentRecord(
                member_id=member_id,
                type=row.document_type,
                facility=row.facility,
                status="received" if row.status == "received" else "requested",
                requested_at=row.requested_at,
                received_at=row.received_at,
                document_id=doc.value.get("document_id") if doc else None,
                evidence=evidence,
            )
        )
    for fact in received:  # documents pushed to us without a query
        if fact.id in matched:
            continue
        session.add(
            DocumentRecord(
                member_id=fact.member_id,
                type=fact.value["document_type"],
                facility=fact.value.get("facility"),
                status="received",
                requested_at=None,
                received_at=fact.loaded_at,
                document_id=fact.value.get("document_id"),
                evidence=[{"fact_id": fact.id}],
            )
        )


def rebuild_projections(session: Session, clock: Clock) -> None:
    today = clock.now().astimezone(PLAN_TZ).date()
    for model in (ContactPoint, ConsentRecord, DocumentRecord):
        session.execute(delete(model))
    facts = visible_facts(session)
    consents = _rebuild_consents(session, facts)
    session.flush()
    _rebuild_contacts(session, facts, consents, today)
    _rebuild_documents(session, facts)
    session.flush()
