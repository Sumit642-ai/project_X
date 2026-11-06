from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.core.config import get_settings
from app.datalayer_mock.identity.models import DailyMetric, Member
from app.facts.snapshot import MemberSnapshot, member_snapshot
from app.signals.base import Rule, Signal
from app.signals.calendar import BusinessCalendar
from app.signals.models import SignalRecord
from app.signals.rules import RULES


def active_rules(
    disabled: Iterable[str] | None = None, calendar: BusinessCalendar | None = None
) -> list[Rule]:
    """All rules except those switched off (settings.disabled_rules unless given)."""
    off = set(get_settings().disabled_rules if disabled is None else disabled)
    return [rule(calendar) for rule in RULES if rule.rule_id not in off]


def to_record(signal: Signal, run_day: date, clock: Clock) -> SignalRecord:
    return SignalRecord(
        run_day=run_day,
        evaluated_at=clock.now(),
        member_id=signal.member_id,
        rule_id=signal.rule_id,
        rule_version=signal.rule_version,
        severity=signal.severity,
        insight_text=signal.insight_text,
        suggested_step=signal.suggested_step,
        input_fact_ids=list(signal.input_fact_ids),
        due_at=signal.due_at,
        due_tz=signal.due_tz,
        deadline_kind=signal.deadline_kind,
        lever=signal.lever,
        key_input_fact_id=signal.key_input_fact_id,
        key_input_date=signal.key_input_date,
    )


def evaluate_member(snapshot: MemberSnapshot, clock: Clock, rules: list[Rule]) -> list[Signal]:
    return [signal for rule in rules for signal in rule.evaluate(snapshot, clock)]


@dataclass
class SignalRun:
    signals: list[SignalRecord]
    counts: dict[str, int]
    snapshots: dict[str, MemberSnapshot]


def evaluate_signals(
    session: Session,
    clock: Clock,
    *,
    disabled: Iterable[str] | None = None,
    calendar: BusinessCalendar | None = None,
) -> SignalRun:
    """Evaluate every enabled rule for every member and store today's signals and counts."""
    run_day = clock.now().astimezone(PLAN_TZ).date()
    rules = active_rules(disabled, calendar)
    session.execute(delete(SignalRecord).where(SignalRecord.run_day == run_day))
    records: list[SignalRecord] = []
    snapshots: dict[str, MemberSnapshot] = {}
    counts = {rule.rule_id: 0 for rule in rules}
    for member_id in session.scalars(select(Member.member_id).order_by(Member.member_id)):
        snapshot = member_snapshot(session, member_id, clock=clock)
        snapshots[member_id] = snapshot
        for signal in evaluate_member(snapshot, clock, rules):
            counts[signal.rule_id] += 1
            records.append(to_record(signal, run_day, clock))
    session.add_all(records)
    for rule_id, count in counts.items():
        metric_name = f"signals.{rule_id}"
        metric = session.scalar(
            select(DailyMetric).where(DailyMetric.metric == metric_name, DailyMetric.day == run_day)
        )
        if metric is None:
            metric = DailyMetric(metric=metric_name, day=run_day)
            session.add(metric)
        metric.value, metric.computed_at = count, clock.now()
    session.flush()
    return SignalRun(records, counts, snapshots)
