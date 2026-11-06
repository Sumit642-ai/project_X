"""Facts (append-only) and the projections built from them.

A Fact is never updated in place or deleted. The single permitted write after insert is
setting superseded_by once, from NULL to the id of the correcting Fact. This is enforced here
(ORM events) and in the database (triggers in migration 0003).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

JsonDoc = JSON().with_variant(JSONB(), "postgresql")

FACT_TYPES = (
    "medication",
    "diagnosis",
    "event",
    "lab",
    "contact_point",
    "sdoh",
    "coverage",
    "care_gap",
    "consent",
    "appointment",
    "service",
    "preference",
    "risk",
)
FACT_STATUSES = ("raw", "member_reported", "cm_confirmed")
# part2: allowlisted program; unverified: unknown program (masked until classified)
SENSITIVITIES = ("none", "part2", "unverified")
CONFLICT_STATUSES = ("open", "sent_to_prescriber", "resolved")
OWNERS = ("self", "representative", "third_party")
CONSENT_TYPES = ("tcpa_sms", "part2", "personal_representative", "third_party_release")
DOCUMENT_STATUSES = ("requested", "received", "not_available")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint(_in("type", FACT_TYPES), name="ck_facts_type"),
        CheckConstraint(_in("status", FACT_STATUSES), name="ck_facts_status"),
        CheckConstraint(_in("sensitivity", SENSITIVITIES), name="ck_facts_sensitivity"),
        Index("ix_facts_member_type_key", "member_id", "type", "key"),
        Index("ix_facts_source", "source_system", "source_record_id", "type", "key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"))
    # The identity link that attributed the source record to this member. Facts behind a
    # link that is later rejected or unmerged stay stored but drop out of member views.
    link_id: Mapped[int | None] = mapped_column(ForeignKey("member_links.id"))
    type: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
    source_system: Mapped[str] = mapped_column(String(60))
    source_record_id: Mapped[str] = mapped_column(String(120))
    load_id: Mapped[int | None] = mapped_column(ForeignKey("loads.id"))
    source_row: Mapped[int | None] = mapped_column(Integer)
    event_date: Mapped[date | None] = mapped_column(Date)
    loaded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(20), default="raw")
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("facts.id"))
    sensitivity: Mapped[str] = mapped_column(String(10), default="none")
    value_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class FactImmutableError(RuntimeError):
    pass


@event.listens_for(Fact, "before_update")
def _only_supersede(mapper: Mapper[Fact], connection: Any, target: Fact) -> None:
    state = inspect(target)
    for attr in state.attrs:
        history = attr.history
        if not history.has_changes():
            continue
        if attr.key == "superseded_by" and list(history.deleted) in ([], [None]):
            continue
        raise FactImmutableError(f"facts are append-only: cannot change {attr.key}")


@event.listens_for(Fact, "before_delete")
def _never_delete(mapper: Mapper[Fact], connection: Any, target: Fact) -> None:
    raise FactImmutableError("facts are append-only: cannot delete")


class Conflict(Base):
    __tablename__ = "conflicts"
    __table_args__ = (
        CheckConstraint(_in("status", CONFLICT_STATUSES), name="ck_conflicts_status"),
        CheckConstraint(_in("kind", ("dose", "presence", "code")), name="ck_conflicts_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    fact_type: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))
    summary: Mapped[str] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="open")
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc)
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ConflictFact(Base):
    """conflicts.fact_ids as a join table, so every id is a real Fact."""

    __tablename__ = "conflict_facts"

    conflict_id: Mapped[int] = mapped_column(ForeignKey("conflicts.id"), primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id"), primary_key=True)


class ContactPoint(Base):
    """Current contact ladder, rebuilt from contact_point and consent Facts."""

    __tablename__ = "contact_points"
    __table_args__ = (CheckConstraint(_in("owner", OWNERS), name="ck_contact_points_owner"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    number: Mapped[str] = mapped_column(String(20))
    owner: Mapped[str] = mapped_column(String(20))
    owner_name: Mapped[str | None] = mapped_column(String(120))
    relationship: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str | None] = mapped_column(String(60))
    last_verified: Mapped[date | None] = mapped_column(Date)
    last_outcome: Mapped[str | None] = mapped_column(String(30))
    best_window: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    confidence_factors: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
    consent_sms: Mapped[bool]
    authorised: Mapped[bool]
    callable: Mapped[bool]
    fact_ids: Mapped[list[int]] = mapped_column(JsonDoc)


class ConsentRecord(Base):
    __tablename__ = "consents"
    __table_args__ = (CheckConstraint(_in("type", CONSENT_TYPES), name="ck_consents_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    scope: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    revoked_at: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(20))
    program: Mapped[str | None] = mapped_column(String(120))
    party_name: Mapped[str | None] = mapped_column(String(120))
    relationship: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str | None] = mapped_column(String(120))
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id"))

    def is_valid(self, on: date) -> bool:
        return (
            self.valid_from <= on
            and (self.valid_to is None or on <= self.valid_to)
            and (self.revoked_at is None or on < self.revoked_at)
        )


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(_in("status", DOCUMENT_STATUSES), name="ck_documents_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    facility: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20))
    requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    document_id: Mapped[str | None] = mapped_column(String(40))
    # Staging rows behind this entry: [{"stream", "load_id", "source_row"}, ...]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JsonDoc)
