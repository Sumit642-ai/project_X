from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class WritebackOutbox(Base):
    """A save waiting to reach the CM platform. One row per idempotency key."""

    __tablename__ = "writeback_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'synced', 'conflict', 'alerted')",
            name="ck_writeback_outbox_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    encounter_id: Mapped[int] = mapped_column(ForeignKey("encounters.id"), index=True)
    member_id: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    base_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    first_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cm_version: Mapped[int | None] = mapped_column(Integer)
