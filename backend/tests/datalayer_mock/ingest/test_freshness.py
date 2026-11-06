from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.datalayer_mock.ingest import FeedStatus, feed_status, ingest_file
from app.datalayer_mock.ingest.contracts import FEED_ORDER
from tests.datalayer_mock.ingest.helpers import PHARMACY_COLUMNS, pharmacy_rows, write_pharmacy


def _by_feed(session: Session, clock: FixedClock) -> dict[str, FeedStatus]:
    return {s.feed: s for s in feed_status(session, clock)}


def test_pharmacy_age_follows_the_clock_moved_forward_31_hours(
    session: Session, landing: Path, tmp_path: Path
) -> None:
    path = write_pharmacy(tmp_path, "20261108", pharmacy_rows(10))
    ingest_file(session, path, clock=FixedClock(REFERENCE_INSTANT), landing_root=landing)

    at_load = _by_feed(session, FixedClock(REFERENCE_INSTANT))["pharmacy"]
    later = _by_feed(session, FixedClock(REFERENCE_INSTANT + timedelta(hours=31)))["pharmacy"]

    assert at_load.age_hours == 0.0
    assert later.age_hours == 31.0
    assert later.last_good_load_at == REFERENCE_INSTANT
    assert later.data_as_of is not None and later.data_as_of.isoformat() == "2026-11-08"


def test_feeds_never_loaded_are_unknown_not_zero(session: Session, clock: FixedClock) -> None:
    statuses = feed_status(session, clock)

    assert [s.feed for s in statuses] == list(FEED_ORDER)
    assert all(s.last_good_load_at is None and s.age_hours is None for s in statuses)


def test_quarantined_load_does_not_refresh_the_feed(
    session: Session, landing: Path, tmp_path: Path
) -> None:
    good = write_pharmacy(tmp_path, "20261101", pharmacy_rows(10))
    ingest_file(session, good, clock=FixedClock(REFERENCE_INSTANT), landing_root=landing)
    columns = [c for c in PHARMACY_COLUMNS if c != "ndc"]
    bad = write_pharmacy(tmp_path, "20261108", pharmacy_rows(10), columns)
    ingest_file(
        session, bad, clock=FixedClock(REFERENCE_INSTANT + timedelta(hours=5)), landing_root=landing
    )

    status = _by_feed(session, FixedClock(REFERENCE_INSTANT + timedelta(hours=10)))["pharmacy"]

    assert status.age_hours == 10.0
