from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

LOG_STATUSES = (
    "ok",
    "timeout",
    "connection",
    "rate_limited",
    "refusal",
    "truncated",
    "invalid_output",
    "not_configured",
    "api_error",
    "error",
)


class AiLog(Base):
    """Every prompt sent and every output received, for audit. Append-only (migration 0009)."""

    __tablename__ = "ai_logs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in LOG_STATUSES)})", name="ck_ai_logs_status"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor: Mapped[str] = mapped_column(String(40))
    feature: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60))
    prompt_version: Mapped[str] = mapped_column(String(30))
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class AiDraft(Base):
    """A validated draft as shown to the nurse: sentences with citations and statuses."""

    __tablename__ = "ai_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id"), index=True)
    ai_log_id: Mapped[int] = mapped_column(ForeignKey("ai_logs.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_by: Mapped[str] = mapped_column(ForeignKey("users.username"))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    note_text: Mapped[str] = mapped_column(Text)
    unsupported_count: Mapped[int] = mapped_column(Integer)
    blocked_count: Mapped[int] = mapped_column(Integer)
    flagged_medications: Mapped[list[str]] = mapped_column(JSON)


class AiGuardrailMetric(Base):
    """Per encounter, recorded when the nurse saves: is the draft helping or being rewritten?"""

    __tablename__ = "ai_guardrail_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id"), unique=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("ai_drafts.id"))
    pod: Mapped[str | None] = mapped_column(String(20), index=True)
    unsupported_count: Mapped[int] = mapped_column(Integer)
    # Word-level edit distance between the drafted note and the saved note, / the longer one.
    edit_distance: Mapped[float] = mapped_column(Float)
    major_edit: Mapped[bool] = mapped_column()  # edit_distance > 0.3
    seconds_to_save: Mapped[int] = mapped_column(Integer)  # draft shown -> nurse saved
    saved_at: Mapped[datetime] = mapped_column(UTCDateTime())
