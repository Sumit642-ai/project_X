from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class MemberScore(Base):
    """Score = 40R + 30U + 20M + 10A for one member on one run day, with every input."""

    __tablename__ = "member_scores"
    __table_args__ = (UniqueConstraint("run_day", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_day: Mapped[date] = mapped_column(Date, index=True)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    r: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    r_source: Mapped[str] = mapped_column(String(20))  # plan | cohort_median
    verify: Mapped[bool]  # R was not supplied by the plan: verify before relying on it
    u: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    u_deadline: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    u_clinical: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    hours_to_deadline: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deadline_source: Mapped[str | None] = mapped_column(Text)
    m: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    m_lever: Mapped[str | None] = mapped_column(String(40))
    m_key_input_date: Mapped[date | None] = mapped_column(Date)
    a: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    a_contact: Mapped[str | None] = mapped_column(String(20))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    tier: Mapped[str] = mapped_column(String(2))
    rank: Mapped[int] = mapped_column(Integer)
    components: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_fact_ids: Mapped[list[int]] = mapped_column(JSON)
    input_signal_ids: Mapped[list[int]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
