from datetime import date, datetime

from sqlalchemy import Column, Date, ForeignKey, Integer, MetaData, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime

RECEIVED, PASS, QUARANTINE = "RECEIVED", "PASS", "QUARANTINE"


class Load(Base):
    """One raw file (or one real-time ADT message) received from a feed."""

    __tablename__ = "loads"

    id: Mapped[int] = mapped_column(primary_key=True)
    feed: Mapped[str] = mapped_column(String(40), index=True)
    stream: Mapped[str] = mapped_column(String(60), index=True)
    file: Mapped[str] = mapped_column(String(300))
    landing_path: Mapped[str | None] = mapped_column(String(400))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    loaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(12), default=RECEIVED)
    row_count: Mapped[int | None] = mapped_column(Integer)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False)
    data_as_of: Mapped[date | None] = mapped_column(Date)


class LoadError(Base):
    """A row that failed its contract. Kept for PASS loads (<= 2%) and QUARANTINE loads alike."""

    __tablename__ = "load_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    load_id: Mapped[int] = mapped_column(ForeignKey("loads.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str] = mapped_column(Text)


# Views are not part of Base.metadata, so create_all/autogenerate never turn them into tables.
# The view itself is created in migration 0001.
view_metadata = MetaData()

feed_last_good_load = Table(
    "feed_last_good_load",
    view_metadata,
    Column("feed", String(40)),
    Column("last_good_load_at", UTCDateTime()),
    Column("data_as_of", Date),
)
