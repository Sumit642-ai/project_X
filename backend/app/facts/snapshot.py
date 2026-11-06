from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity.models import NEEDS_REVIEW, Member, MemberLink
from app.facts.conflicts import conflict_fact_ids
from app.facts.freshness import Freshness, freshness
from app.facts.models import Conflict, ConsentRecord, ContactPoint, DocumentRecord, Fact
from app.facts.projections import visible_facts

PART2_MASK = {
    "masked": True,
    "reason": "42 CFR Part 2 program record: reveal needs valid consent and is audited",
}


@dataclass(frozen=True)
class FactView:
    fact: Fact
    value: dict[str, Any]  # masked for Part 2 records
    freshness: Freshness
    masked: bool


@dataclass(frozen=True)
class ConflictView:
    conflict: Conflict
    fact_ids: list[int]


@dataclass(frozen=True)
class ConsentView:
    consent: ConsentRecord
    valid: bool


@dataclass
class MemberSnapshot:
    member: Member
    facts: list[FactView]
    conflicts: list[ConflictView]
    documents: list[DocumentRecord]
    contacts: list[ContactPoint]  # contact ladder: callable first, then by confidence
    consents: list[ConsentView]
    pending_links: list[MemberLink] = field(default_factory=list)  # identity review queue

    def facts_of(self, fact_type: str, key: str | None = None) -> list[FactView]:
        return [
            f for f in self.facts if f.fact.type == fact_type and (key is None or f.fact.key == key)
        ]


def member_snapshot(session: Session, member_id: str, *, clock: Clock) -> MemberSnapshot:
    member = session.get(Member, member_id)
    if member is None:
        raise KeyError(member_id)
    today = clock.now().astimezone(PLAN_TZ).date()
    facts = [
        FactView(
            f,
            PART2_MASK if policy.is_masked(f) else f.value,
            freshness(f, clock),
            policy.is_masked(f),
        )
        for f in visible_facts(session, member_id)
        if f.event_date is None or f.event_date <= today  # the member as of the clock
    ]
    conflicts = [
        ConflictView(c, conflict_fact_ids(session, c.id))
        for c in session.scalars(
            select(Conflict).where(Conflict.member_id == member_id).order_by(Conflict.id)
        )
    ]
    documents = list(
        session.scalars(
            select(DocumentRecord)
            .where(DocumentRecord.member_id == member_id)
            .order_by(DocumentRecord.id)
        )
    )
    contacts = sorted(
        session.scalars(select(ContactPoint).where(ContactPoint.member_id == member_id)),
        key=lambda c: (not c.callable, -c.confidence, c.number),
    )
    consents = [
        ConsentView(c, policy.consent_is_valid(c, today))
        for c in session.scalars(
            select(ConsentRecord)
            .where(ConsentRecord.member_id == member_id)
            .order_by(ConsentRecord.id)
        )
    ]
    pending = list(
        session.scalars(
            select(MemberLink)
            .where(MemberLink.member_id == member_id, MemberLink.status == NEEDS_REVIEW)
            .order_by(MemberLink.id)
        )
    )
    return MemberSnapshot(member, facts, conflicts, documents, contacts, consents, pending)
