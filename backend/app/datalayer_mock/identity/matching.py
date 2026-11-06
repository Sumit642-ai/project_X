"""Golden records and links.

Deterministic: an exact plan member ID that exists in members -> confidence 1.0, auto_linked.
Probabilistic (records without a usable plan ID): weighted scorer; >= 0.90 auto_linked only
when it is the single candidate at or above 0.70; 0.70-0.89 needs_review; below 0.70 no link.
A pair that already has a link row, in any status, is never touched again, so rejected pairs
are never re-suggested and human decisions are never overwritten.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.datalayer_mock.identity.models import (
    AUTO_LINKED,
    NEEDS_REVIEW,
    LinkAudit,
    Member,
    MemberLink,
)
from app.datalayer_mock.identity.scoring import (
    REVIEW_THRESHOLD,
    Demographics,
    MatchScore,
    classify,
    normalise_name,
    score,
)
from app.datalayer_mock.identity.sources import SourceRecord, active_rows, extract_sources

MATCHER = "system:matcher"


@dataclass
class MatchSummary:
    created: dict[str, int] = field(default_factory=dict)
    skipped_existing: int = 0
    unmatched: list[str] = field(default_factory=list)

    def count(self, status: str) -> None:
        self.created[status] = self.created.get(status, 0) + 1


def build_golden_records(session: Session, clock: Clock) -> dict[str, Member]:
    """One member per plan ID with active coverage on the clock's date."""
    today = clock.now().astimezone(PLAN_TZ).date()
    existing = {m.member_id: m for m in session.scalars(select(Member))}
    for row in active_rows(session, "eligibility_834"):
        if row.term_date is not None and row.term_date < today:
            continue
        member = existing.get(row.member_id)
        if member is None:
            member = Member(member_id=row.member_id)
            session.add(member)
            existing[row.member_id] = member
        member.last_name, member.first_name, member.dob = row.last_name, row.first_name, row.dob
        member.sex, member.lob, member.phone = row.sex, row.lob, row.phone
        member.address_line1, member.city, member.zip = row.address_line1, row.city, row.zip
        member.source_load_id, member.source_row = row.load_id, row.source_row
        member.refreshed_at = clock.now()
    session.flush()
    return existing


def member_demographics(member: Member) -> Demographics:
    return Demographics(
        member.first_name,
        member.last_name,
        member.dob,
        member.sex,
        member.address_line1,
        member.city,
        member.zip,
        member.phone,
    )


def candidates(source: Demographics, members: dict[str, Member]) -> list[Member]:
    """Blocking: same DOB, same normalised surname, or same phone."""
    last = normalise_name(source.last_name)
    return [
        m
        for m in members.values()
        if (source.dob is not None and m.dob == source.dob)
        or (last is not None and normalise_name(m.last_name) == last)
        or (source.phone is not None and m.phone == source.phone)
    ]


def _member_ref(member: Member) -> dict[str, object]:
    return {
        "stream": "eligibility_834",
        "load_id": member.source_load_id,
        "source_row": member.source_row,
        "role": "golden record",
    }


def run_matching(session: Session, clock: Clock) -> MatchSummary:
    members = build_golden_records(session, clock)
    existing = {
        (link.source_system, link.source_record_id, link.member_id)
        for link in session.scalars(select(MemberLink))
    }
    summary = MatchSummary()

    def create(
        source: SourceRecord,
        member: Member,
        method: str,
        confidence: Decimal,
        status: str,
        match: MatchScore | None,
    ) -> None:
        key = (source.source_system, source.source_record_id, member.member_id)
        if key in existing:
            summary.skipped_existing += 1
            return
        now = clock.now()
        link = MemberLink(
            source_system=source.source_system,
            source_record_id=source.source_record_id,
            member_id=member.member_id,
            match_method=method,
            confidence=confidence,
            status=status,
            field_scores=match.as_json() if match else None,
            evidence=[*source.evidence, _member_ref(member)],
            decided_by=MATCHER if status == AUTO_LINKED else None,
            decided_at=now if status == AUTO_LINKED else None,
            created_at=now,
        )
        session.add(link)
        session.flush()
        session.add(
            LinkAudit(
                link_id=link.id,
                action="auto_linked" if status == AUTO_LINKED else "suggested",
                actor=MATCHER,
                at=now,
                from_status=None,
                to_status=status,
                note=f"{method} confidence {confidence}",
            )
        )
        existing.add(key)
        summary.count(status)

    for source in extract_sources(session, set(members)):
        if source.plan_member_id is not None and source.plan_member_id in members:
            create(
                source,
                members[source.plan_member_id],
                "exact_id",
                Decimal("1.000"),
                AUTO_LINKED,
                None,
            )
            continue
        if source.demographics is None:
            summary.unmatched.append(f"{source.source_system}:{source.source_record_id}")
            continue
        scored = sorted(
            (
                (score(source.demographics, member_demographics(m)), m)
                for m in candidates(source.demographics, members)
            ),
            key=lambda pair: (-pair[0].confidence, pair[1].member_id),
        )
        eligible = [(s, m) for s, m in scored if s.confidence >= REVIEW_THRESHOLD]
        if not eligible:
            summary.unmatched.append(f"{source.source_system}:{source.source_record_id}")
            continue
        for match, member in eligible:
            status = classify(match.confidence)
            if status == AUTO_LINKED and len(eligible) > 1:
                status = NEEDS_REVIEW  # never auto-merge when another candidate is plausible
            create(source, member, "probabilistic", match.confidence, status or NEEDS_REVIEW, match)
    session.flush()
    return summary


def today_in_plan_tz(clock: Clock) -> date:
    return clock.now().astimezone(PLAN_TZ).date()
