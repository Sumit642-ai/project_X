from datetime import date, datetime

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class SignalRecord(Base):
    """A rule firing for a member on a run day. Re-running the same day replaces that day."""

    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_day_member", "run_day", "member_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_day: Mapped[date] = mapped_column(Date)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"))
    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    rule_version: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    insight_text: Mapped[str] = mapped_column(String(120))
    suggested_step: Mapped[str] = mapped_column(Text)
    input_fact_ids: Mapped[list[int]] = mapped_column(JSON)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # stored in UTC
    due_tz: Mapped[str | None] = mapped_column(String(40))  # the member's time zone
    deadline_kind: Mapped[str | None] = mapped_column(String(20))  # member_contact | um | appeal
    lever: Mapped[bool]
    key_input_fact_id: Mapped[int | None] = mapped_column(Integer)
    key_input_date: Mapped[date | None] = mapped_column(Date)
