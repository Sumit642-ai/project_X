from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.datalayer_mock.identity.matching import today_in_plan_tz
from app.datalayer_mock.identity.models import LINKED_STATUSES, DailyMetric, MemberLink
from app.datalayer_mock.identity.sources import active_rows, adt_source_key

UNLINKED_ADT_EVENTS = "unlinked_adt_events"


def unlinked_adt_events(session: Session) -> int:
    """ADT events whose patient is not attributed to a member (auto-linked or confirmed).

    Events waiting in the review queue count as unlinked.
    """
    linked = {
        (link.source_system, link.source_record_id)
        for link in session.scalars(
            select(MemberLink).where(MemberLink.status.in_(LINKED_STATUSES))
        )
    }
    return sum(
        1
        for row in active_rows(session, "adt")
        if adt_source_key(row.assigning_authority, row.patient_id) not in linked
    )


def record_daily_metrics(session: Session, clock: Clock) -> DailyMetric:
    """Store today's unlinked ADT event count (one row per day; re-running updates it)."""
    day = today_in_plan_tz(clock)
    metric = session.scalar(
        select(DailyMetric).where(DailyMetric.metric == UNLINKED_ADT_EVENTS, DailyMetric.day == day)
    )
    if metric is None:
        metric = DailyMetric(metric=UNLINKED_ADT_EVENTS, day=day)
        session.add(metric)
    metric.value = unlinked_adt_events(session)
    metric.computed_at = clock.now()
    session.flush()
    return metric
