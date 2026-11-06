from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.datalayer_mock.ingest.contracts import FEED_ORDER
from app.datalayer_mock.ingest.models import feed_last_good_load


@dataclass(frozen=True)
class FeedStatus:
    feed: str
    last_good_load_at: datetime | None  # None = never loaded: show as UNKNOWN
    age_hours: float | None
    data_as_of: date | None


def feed_status(session: Session, clock: Clock) -> list[FeedStatus]:
    """Per feed: last good load time and its age in hours, measured on the injected clock."""
    now = clock.now()
    rows = {row.feed: row for row in session.execute(select(feed_last_good_load))}
    feeds = list(FEED_ORDER) + sorted(set(rows) - set(FEED_ORDER))
    statuses = []
    for feed in feeds:
        row = rows.get(feed)
        last = row.last_good_load_at if row is not None else None
        age = round((now - last).total_seconds() / 3600, 2) if last is not None else None
        statuses.append(FeedStatus(feed, last, age, row.data_as_of if row is not None else None))
    return statuses
