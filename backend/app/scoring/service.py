from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.encounters.models import SignalHandle
from app.facts.models import Fact
from app.facts.snapshot import member_snapshot
from app.scoring.models import MemberScore
from app.scoring.score import (
    ScoreResult,
    cohort_medians,
    compute_score,
    fmt,
    medians_by_lob,
    rank,
)
from app.signals.base import Signal
from app.signals.calendar import BusinessCalendar
from app.signals.engine import active_rules, evaluate_member, evaluate_signals, to_record
from app.signals.models import SignalRecord


def _as_signal(record: SignalRecord) -> Signal:
    return Signal(
        member_id=record.member_id,
        rule_id=record.rule_id,
        rule_version=record.rule_version,
        input_fact_ids=tuple(record.input_fact_ids),
        insight_text=record.insight_text,
        severity=record.severity,  # type: ignore[arg-type]
        suggested_step=record.suggested_step,
        due_at=record.due_at,
        due_tz=record.due_tz,
        deadline_kind=record.deadline_kind,  # type: ignore[arg-type]
        lever=record.lever,
        key_input_fact_id=record.key_input_fact_id,
        key_input_date=record.key_input_date,
    )


def score_members(
    session: Session,
    clock: Clock,
    *,
    disabled: Iterable[str] | None = None,
    calendar: BusinessCalendar | None = None,
) -> list[MemberScore]:
    """Evaluate signals, score and rank every member, and store the day's scores."""
    run = evaluate_signals(session, clock, disabled=disabled, calendar=calendar)
    run_day = clock.now().astimezone(PLAN_TZ).date()
    by_member: dict[str, list[SignalRecord]] = {}
    for record in run.signals:
        by_member.setdefault(record.member_id, []).append(record)
    medians = cohort_medians(run.snapshots)
    handled = handled_by_member(session)
    results = rank(
        [
            compute_score(
                snapshot,
                [_as_signal(r) for r in by_member.get(member_id, [])],
                clock,
                medians,
                handled=handled.get(member_id, frozenset()),
            )
            for member_id, snapshot in run.snapshots.items()
        ]
    )
    session.execute(delete(MemberScore).where(MemberScore.run_day == run_day))
    rows = [
        _row(result, position, run_day, clock, by_member.get(result.member_id, []))
        for position, result in enumerate(results, start=1)
    ]
    session.add_all(rows)
    session.flush()
    return rows


def _row(
    result: ScoreResult, position: int, run_day: object, clock: Clock, records: list[SignalRecord]
) -> MemberScore:
    return MemberScore(
        run_day=run_day,
        computed_at=clock.now(),
        member_id=result.member_id,
        r=result.r.value,
        r_source=result.r.source,
        verify=result.r.verify,
        u=result.u,
        u_deadline=result.u_deadline,
        u_clinical=result.u_clinical,
        hours_to_deadline=result.hours_to_deadline,
        deadline_at=result.deadline_at,
        deadline_source=result.deadline_source,
        m=result.m,
        m_lever=result.m_lever,
        m_key_input_date=result.m_key_input_date,
        a=result.a,
        a_contact=result.a_contact,
        score=result.score,
        tier=result.tier,
        rank=position,
        components={k: fmt(v) for k, v in result.parts.items()},
        input_fact_ids=result.input_fact_ids,
        input_signal_ids=[r.id for r in records],
        explanation=result.explanation(),
    )


def explain(session: Session, member_id: str) -> str:
    """The latest stored score for a member as arithmetic, e.g. '35.2 + 30 + 20 + 8.2 = 93.4'."""
    row = session.scalars(
        select(MemberScore)
        .where(MemberScore.member_id == member_id)
        .order_by(MemberScore.run_day.desc(), MemberScore.id.desc())
    ).first()
    if row is None:
        raise KeyError(f"no score stored for {member_id}")
    return row.explanation


def queue(session: Session, clock: Clock) -> list[MemberScore]:
    run_day = clock.now().astimezone(PLAN_TZ).date()
    return list(
        session.scalars(
            select(MemberScore).where(MemberScore.run_day == run_day).order_by(MemberScore.rank)
        )
    )


def handled_by_member(session: Session) -> dict[str, frozenset[tuple[str, tuple[int, ...]]]]:
    keys: dict[str, set[tuple[str, tuple[int, ...]]]] = {}
    for handle in session.scalars(select(SignalHandle)):
        keys.setdefault(handle.member_id, set()).add(
            (handle.rule_id, tuple(sorted(handle.input_fact_ids)))
        )
    return {member: frozenset(v) for member, v in keys.items()}


def _stored_medians(session: Session) -> dict[str | None, Decimal]:
    lob = {
        f.member_id: f.value.get("lob")
        for f in session.scalars(
            select(Fact).where(
                Fact.type == "coverage", Fact.key.like("plan:%"), Fact.superseded_by.is_(None)
            )
        )
    }
    pairs = [
        (lob.get(f.member_id), Decimal(str(f.value["score"])))
        for f in session.scalars(
            select(Fact).where(Fact.type == "risk", Fact.superseded_by.is_(None))
        )
    ]
    return medians_by_lob(pairs)


def rescore_member(session: Session, member_id: str, clock: Clock) -> MemberScore:
    """Re-evaluate one member after a decision (e.g. a confirmed link) and re-rank the day."""
    run_day = clock.now().astimezone(PLAN_TZ).date()
    snapshot = member_snapshot(session, member_id, clock=clock)
    signals = evaluate_member(snapshot, clock, active_rules())
    session.execute(
        delete(SignalRecord).where(
            SignalRecord.run_day == run_day, SignalRecord.member_id == member_id
        )
    )
    records = [to_record(signal, run_day, clock) for signal in signals]
    session.add_all(records)
    session.flush()
    result = compute_score(
        snapshot,
        signals,
        clock,
        _stored_medians(session),
        handled=handled_by_member(session).get(member_id, frozenset()),
    )
    session.execute(
        delete(MemberScore).where(
            MemberScore.run_day == run_day, MemberScore.member_id == member_id
        )
    )
    row = _row(result, 0, run_day, clock, records)
    session.add(row)
    session.flush()
    day_rows = list(session.scalars(select(MemberScore).where(MemberScore.run_day == run_day)))
    for position, other in enumerate(
        sorted(day_rows, key=lambda r: (r.tier, -r.score, r.member_id)), start=1
    ):
        other.rank = position
    session.flush()
    return row
