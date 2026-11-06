from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

AUTO_LINKED = "auto_linked"
NEEDS_REVIEW = "needs_review"
REJECTED = "rejected"
CONFIRMED = "confirmed"
LINKED_STATUSES = (AUTO_LINKED, CONFIRMED)


class Member(Base):
    """Golden record, built from the active eligibility row carrying this plan member ID."""

    __tablename__ = "members"

    member_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_name: Mapped[str] = mapped_column(String(80))
    first_name: Mapped[str] = mapped_column(String(80))
    dob: Mapped[date] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(2))
    lob: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(20))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(80))
    zip: Mapped[str | None] = mapped_column(String(10))
    source_load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"))
    source_row: Mapped[int] = mapped_column(Integer)
    refreshed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class MemberLink(Base):
    """A source record (by system and ID) attributed, or proposed, to a golden member."""

    __tablename__ = "member_links"
    __table_args__ = (UniqueConstraint("source_system", "source_record_id", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_system: Mapped[str] = mapped_column(String(60), index=True)
    source_record_id: Mapped[str] = mapped_column(String(80), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    match_method: Mapped[str] = mapped_column(String(20))  # exact_id | probabilistic
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(20))
    # Per-field level, score and contribution for probabilistic matches.
    field_scores: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Staging rows the decision used: [{"stream", "load_id", "source_row"}, ...].
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class LinkAudit(Base):
    __tablename__ = "link_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("member_links.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # auto_linked|suggested|confirmed|...
    actor: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)


class DailyMetric(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (UniqueConstraint("metric", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    metric: Mapped[str] = mapped_column(String(60))
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime())
