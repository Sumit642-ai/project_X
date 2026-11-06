"""Back-test: does our daily top-N catch readmissions earlier than simpler orderings?

For each historical day, the candidates are members discharged in the previous 30 days and
not yet readmitted. Three orderings pick a daily top-N:
  casecompass  tier, then score (this module's score at 08:00 that day)
  arrival      the order the discharge notifications arrived
  risk_only    the plan risk score alone
A readmission is captured by an ordering when the member was in its top-N on at least one day
after discharge and on or before the readmission day.

Limitation for now: the plan risk feed has a single scoring date (2026-11-01), so every
historical day uses that score. That leaks a little future information into R for all orderings.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, FixedClock
from app.facts.models import Fact
from app.facts.snapshot import member_snapshot
from app.scoring.score import RiskInput, compute_score
from app.signals.engine import active_rules, evaluate_member

HEROES = ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")
READMISSION_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class Candidate:
    member_id: str
    arrival_at: datetime
    risk: Decimal
    tier: str
    score: Decimal


@dataclass(frozen=True)
class Readmission:
    member_id: str
    discharge_day: date
    readmit_day: date


@dataclass
class OrderingResult:
    name: str
    captured: list[str] = field(default_factory=list)
    total: int = 0

    @property
    def rate(self) -> float | None:
        return len(self.captured) / self.total if self.total else None


@dataclass
class BacktestResult:
    days: int
    discharges: int
    readmissions: list[Readmission]
    orderings: dict[str, OrderingResult]

    def summary(self) -> str:
        lines = [
            f"{self.days} days, {self.discharges} discharges, "
            f"{len(self.readmissions)} readmissions within 30 days"
        ]
        for result in self.orderings.values():
            rate = "n/a" if result.rate is None else f"{result.rate:.0%}"
            lines.append(
                f"  {result.name:<12} captured {len(result.captured)}/{result.total} ({rate})"
            )
        return "\n".join(lines)


ORDERINGS: dict[str, Callable[[Candidate], tuple[object, ...]]] = {
    "casecompass": lambda c: (c.tier, -c.score, c.member_id),
    "arrival": lambda c: (c.arrival_at, c.member_id),
    "risk_only": lambda c: (-c.risk, c.member_id),
}


def compare(
    daily: dict[date, list[Candidate]], readmissions: list[Readmission], top_n: int = 12
) -> dict[str, OrderingResult]:
    results = {}
    for name, key in ORDERINGS.items():
        picked = {
            day: {c.member_id for c in sorted(candidates, key=key)[:top_n]}
            for day, candidates in daily.items()
        }
        result = OrderingResult(name, total=len(readmissions))
        for event in readmissions:
            if any(
                event.member_id in members
                for day, members in picked.items()
                if event.discharge_day < day <= event.readmit_day
            ):
                result.captured.append(event.member_id)
        results[name] = result
    return results


def _inpatient(session: Session, key: str, stamp: str) -> dict[str, list[tuple[date, datetime]]]:
    found: dict[str, list[tuple[date, datetime]]] = {}
    for fact in session.scalars(
        select(Fact).where(Fact.type == "event", Fact.key == key, Fact.superseded_by.is_(None))
    ):
        when = fact.value.get(stamp)
        arrived = fact.value.get("message_at")
        if fact.value.get("patient_class") != "I" or not when or not arrived:
            continue
        day = datetime.fromisoformat(when).astimezone(PLAN_TZ).date()
        found.setdefault(fact.member_id, []).append((day, datetime.fromisoformat(arrived)))
    return found


def backtest(
    session: Session, start: date, end: date, *, top_n: int = 12, exclude: tuple[str, ...] = HEROES
) -> BacktestResult:
    discharges = {
        m: v
        for m, v in _inpatient(session, "adt:discharge", "discharge_at").items()
        if m not in exclude
    }
    admissions = _inpatient(session, "adt:admission", "admit_at")
    readmissions = [
        Readmission(member, day, admit)
        for member, events in discharges.items()
        for day, _ in events
        for admit, _ in admissions.get(member, [])
        if day < admit <= day + READMISSION_WINDOW
    ]
    risk = {
        f.member_id: RiskInput(Decimal(str(f.value["score"])), "plan", f.id)
        for f in session.scalars(
            select(Fact).where(Fact.type == "risk", Fact.superseded_by.is_(None))
        )
    }
    median_risk = sorted(r.value for r in risk.values())[len(risk) // 2] if risk else Decimal(0)
    rules = active_rules()
    daily: dict[date, list[Candidate]] = {}
    day = start
    while day <= end:
        clock = FixedClock(datetime.combine(day, time(8, 0), tzinfo=PLAN_TZ))
        candidates = []
        for member, events in sorted(discharges.items()):
            recent = [(d, arrived) for d, arrived in events if day - READMISSION_WINDOW <= d < day]
            if not recent:
                continue
            last_day, arrived = max(recent)
            if any(last_day < a < day for a, _ in admissions.get(member, [])):
                continue  # already readmitted
            snapshot = member_snapshot(session, member, clock=clock)
            member_risk = risk.get(member) or RiskInput(median_risk, "cohort_median", None)
            result = compute_score(
                snapshot,
                evaluate_member(snapshot, clock, rules),
                clock,
                {None: median_risk},
                risk_override=member_risk,
            )
            candidates.append(
                Candidate(member, arrived, member_risk.value, result.tier, result.score)
            )
        if candidates:
            daily[day] = candidates
        day += timedelta(days=1)
    return BacktestResult(
        days=(end - start).days + 1,
        discharges=sum(len(v) for v in discharges.values()),
        readmissions=readmissions,
        orderings=compare(daily, readmissions, top_n),
    )
