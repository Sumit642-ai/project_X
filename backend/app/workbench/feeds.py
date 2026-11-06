"""Feed freshness against expected cadence: which streams are stale right now."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.core.config import get_settings
from app.datalayer_mock.ingest.contracts import CONTRACTS, FEED_ORDER
from app.datalayer_mock.ingest.models import PASS, Load
from app.demo.state import paused_feeds

# Expected maximum age of the last good load, by feed.
LOAD_SLA_HOURS: dict[str, int] = {
    "adt": 30,
    "pharmacy": 30,
    "eligibility": 30,
    "cm_platform": 30,
    "documents": 30,
    "labs": 30,
    "care_gaps": 30,
    "um": 30,
    "sdoh": 30,
    "claims": 8 * 24,
    "formulary": 35 * 24,
    "risk": 35 * 24,
    "part2": 35 * 24,
    "medicaid": 35 * 24,
}
# Expected maximum age of the data itself (its as-of date), by stream.
DATA_SLA_DAYS: dict[str, int] = {"claims_837": 30, "ltss_aide_hours": 30}


@dataclass(frozen=True)
class StreamStatus:
    feed: str
    stream: str
    last_good_load_at: datetime | None
    age_hours: float | None
    data_as_of: date | None
    data_age_days: int | None
    stale: bool
    reason: str | None


def stream_statuses(session: Session, clock: Clock) -> list[StreamStatus]:
    now = clock.now()
    today = now.astimezone(PLAN_TZ).date()
    latest: dict[str, Any] = {}
    for good in session.execute(
        select(Load.stream, Load.loaded_at, Load.data_as_of)
        .where(Load.status == PASS)
        .order_by(Load.id)
    ):
        if good.loaded_at is not None and good.loaded_at <= now:
            latest[good.stream] = good
    paused = set(paused_feeds(get_settings()))  # demo operator panel only
    statuses = []
    for contract in sorted(CONTRACTS.values(), key=lambda c: (FEED_ORDER.index(c.feed), c.stream)):
        load = latest.get(contract.stream)
        if load is None or load.loaded_at is None:
            statuses.append(
                StreamStatus(
                    contract.feed, contract.stream, None, None, None, None, True, "never received"
                )
            )
            continue
        age = round((now - load.loaded_at).total_seconds() / 3600, 1)
        data_age = (today - load.data_as_of).days if load.data_as_of else None
        reasons = []
        sla = LOAD_SLA_HOURS.get(contract.feed)
        if sla is not None and age > sla:
            reasons.append(f"last load {age:g} h ago (expected within {sla} h)")
        if contract.feed in paused:
            reasons.append(
                f"feed paused at the data layer: no new files since {_hhmm(load.loaded_at)}"
            )
        data_sla = DATA_SLA_DAYS.get(contract.stream)
        if data_sla is not None and data_age is not None and data_age > data_sla:
            reasons.append(f"data as of {load.data_as_of} ({data_age} days)")
        statuses.append(
            StreamStatus(
                contract.feed,
                contract.stream,
                load.loaded_at,
                age,
                load.data_as_of,
                data_age,
                bool(reasons),
                "; ".join(reasons) or None,
            )
        )
    return statuses


def _hhmm(when: datetime) -> str:
    return when.astimezone(PLAN_TZ).strftime("%a %H:%M")


def stale_streams(session: Session, clock: Clock) -> list[StreamStatus]:
    return [s for s in stream_statuses(session, clock) if s.stale]
