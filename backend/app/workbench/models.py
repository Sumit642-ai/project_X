from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

ROLES = ("cm", "supervisor", "call_agent")


class User(Base):
    """Seeded demo users. Licensure and languages drive assignment checks."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('cm', 'supervisor', 'call_agent')", name="ck_users_role"),
    )

    username: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    credential: Mapped[str | None] = mapped_column(String(20))
    program: Mapped[str | None] = mapped_column(String(40))
    licensed_states: Mapped[list[str]] = mapped_column(JSON)
    languages: Mapped[list[str]] = mapped_column(JSON)
    capacity_target: Mapped[int | None] = mapped_column(Integer)
    # Team the user works in; features in a pilot (the AI note draft) are switched on per pod.
    pod: Mapped[str | None] = mapped_column(String(20))


class Assignment(Base):
    """Who manages a member. History is kept: closing an assignment never deletes it."""

    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'declined', 'reassigned')", name="ck_assignments_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    cm_username: Mapped[str] = mapped_column(ForeignKey("users.username"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    assigned_by: Mapped[str] = mapped_column(String(40))
    assigned_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    reason: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    object_type: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[str] = mapped_column(String(60))
    member_id: Mapped[str | None] = mapped_column(String(40), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(UTCDateTime())


class Snooze(Base):
    """A CM hides a member from their queue until a return date (with a reason)."""

    __tablename__ = "snoozes"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    cm_username: Mapped[str] = mapped_column(ForeignKey("users.username"), index=True)
    until: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
