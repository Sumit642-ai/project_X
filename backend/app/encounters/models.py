from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

OUTCOMES = ("connected", "voicemail", "no_answer", "disconnected", "wrong_person", "declined")
ENCOUNTER_STATUSES = ("open", "wrapped", "saved", "syncing", "synced")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (
        CheckConstraint(_in("status", ENCOUNTER_STATUSES), name="ck_encounters_status"),
        CheckConstraint(
            f"outcome IS NULL OR {_in('outcome', OUTCOMES)}", name="ck_encounters_outcome"
        ),
        CheckConstraint("channel IN ('phone', 'sms', 'video')", name="ck_encounters_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    cm_id: Mapped[str] = mapped_column(ForeignKey("users.username"), index=True)
    channel: Mapped[str] = mapped_column(String(10))
    number_used: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    outcome: Mapped[str | None] = mapped_column(String(20))
    transcription_consent: Mapped[bool] = mapped_column(default=False)
    identity_verified: Mapped[bool] = mapped_column(default=False)
    interpreter_booked: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")
    autosave: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    autosaved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    clinical_concern: Mapped[bool] = mapped_column(default=False)
    crisis: Mapped[bool] = mapped_column(default=False)
    # CM record version when the nurse opened the call (write-back is conditional on it).
    cm_base_version: Mapped[int | None] = mapped_column(Integer)
    # Conflicts the nurse resolved during the call; they close when the save syncs.
    conflict_resolutions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class EncounterField(Base):
    """One assessment field in one encounter: what was prefilled, and what the nurse did."""

    __tablename__ = "encounter_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id"), index=True)
    field_id: Mapped[str] = mapped_column(String(40))
    group: Mapped[str] = mapped_column(String(30))
    label: Mapped[str] = mapped_column(String(120))
    risk: Mapped[str] = mapped_column(String(10))  # high | low
    status: Mapped[str] = mapped_column(String(20))  # prefilled_fresh | prefilled_stale | live_only
    reason: Mapped[str | None] = mapped_column(Text)
    prefill: Mapped[Any | None] = mapped_column(JSON)
    source_fact_ids: Mapped[list[int]] = mapped_column(JSON)
    source_as_of: Mapped[date | None] = mapped_column(Date)
    answer: Mapped[Any | None] = mapped_column(JSON)
    confirmed: Mapped[bool] = mapped_column(default=False)
    method: Mapped[str | None] = mapped_column(String(10))  # single | bulk
    confirmed_by: Mapped[str | None] = mapped_column(String(40))
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    time_on_field_ms: Mapped[int | None] = mapped_column(Integer)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_tasks_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    encounter_id: Mapped[int | None] = mapped_column(ForeignKey("encounters.id"))
    kind: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="open")
    assigned_to: Mapped[str] = mapped_column(String(40))
    signal_rule_id: Mapped[str | None] = mapped_column(String(40))
    signal_input_fact_ids: Mapped[list[int]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # Set when new data shows the task is no longer needed (e.g. the fill arrived): which
    # Facts showed it, and a plain sentence. A person never has to close it by hand.
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_fact_ids: Mapped[list[int] | None] = mapped_column(JSON)


class SignalHandle(Base):
    """A signal a person has acted on (via a task). It stops counting toward U_clinical."""

    __tablename__ = "signal_handles"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("members.member_id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(40))
    input_fact_ids: Mapped[list[int]] = mapped_column(JSON)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    handled_by: Mapped[str] = mapped_column(String(40))
    handled_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    member_id: Mapped[str | None] = mapped_column(String(40))
    encounter_id: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
