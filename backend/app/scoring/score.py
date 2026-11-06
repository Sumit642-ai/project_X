"""Score = 40R + 30U + 20M + 10A (each input 0-1). Pure functions; no database access.

R  plan risk score; cohort median (same line of business) with a VERIFY flag when missing
U  max(U_deadline, U_clinical)
   U_deadline = clamp(1 - h/120, 0, 1), h = hours to the earliest member-contact deadline
   (rule deadlines and open care-gap due dates at 17:00 local; UM-owned deadlines excluded)
   U_clinical = 1.0 red signal, 0.6 amber, 0.3 routine contact due (info signal), else 0
M  1.0 if a fixable lever exists, x 0.75 when the lever's key input is older than 30 days
A  confidence of the best authorised, callable contact point
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.consent import policy
from app.core.clock import PLAN_TZ, Clock
from app.facts.snapshot import MemberSnapshot
from app.signals.base import Signal
from app.signals.calendar import due_at
from app.signals.evidence import (
    d,
    facts,
    member_tz,
    open_care_gaps,
    successful_contact_since,
)

WEIGHTS = {"R": Decimal(40), "U": Decimal(30), "M": Decimal(20), "A": Decimal(10)}
U_WINDOW_HOURS = Decimal(120)
U_CLINICAL = {"red": Decimal("1.0"), "amber": Decimal("0.6"), "info": Decimal("0.3")}
M_LEVER = Decimal("1.0")
M_STALE_FACTOR = Decimal("0.75")
M_STALE_DAYS = 30
CONTACT_MEASURES = ("TRC",)  # met by a member contact; FMC/FUH need a visit


@dataclass(frozen=True)
class RiskInput:
    value: Decimal
    source: str  # plan | cohort_median
    fact_id: int | None

    @property
    def verify(self) -> bool:
        return self.source != "plan"


@dataclass
class ScoreResult:
    member_id: str
    r: RiskInput
    u: Decimal
    u_deadline: Decimal
    u_clinical: Decimal
    hours_to_deadline: Decimal | None
    deadline_at: datetime | None
    deadline_source: str | None
    m: Decimal
    m_lever: str | None
    m_key_input_date: date | None
    a: Decimal
    a_contact: str | None
    score: Decimal
    tier: str
    parts: dict[str, Decimal]
    input_fact_ids: list[int] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)

    def explanation(self) -> str:
        terms = " + ".join(fmt(self.parts[k]) for k in ("R", "U", "M", "A"))
        return f"{terms} = {fmt(self.score)}"


def fmt(value: Decimal) -> str:
    text = f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):f}"
    return text.rstrip("0").rstrip(".")


def plan_risk(snapshot: MemberSnapshot) -> RiskInput | None:
    scores = facts(snapshot, "risk", "plan_risk")
    if not scores:
        return None
    best = max(scores, key=lambda f: (f.event_date or date.min, f.id))
    return RiskInput(Decimal(str(best.value["score"])), "plan", best.id)


def line_of_business(snapshot: MemberSnapshot) -> str | None:
    coverage = facts(snapshot, "coverage", "plan:")
    return coverage[-1].value.get("lob") if coverage else None


def cohort_medians(snapshots: dict[str, MemberSnapshot]) -> dict[str | None, Decimal]:
    """Median plan risk by line of business, plus an overall median under key None."""
    pairs = []
    for snapshot in snapshots.values():
        risk = plan_risk(snapshot)
        if risk is not None:
            pairs.append((line_of_business(snapshot), risk.value))
    return medians_by_lob(pairs)


def medians_by_lob(pairs: list[tuple[str | None, Decimal]]) -> dict[str | None, Decimal]:
    by_lob: dict[str | None, list[Decimal]] = {}
    for lob, value in pairs:
        by_lob.setdefault(lob, []).append(value)
        by_lob.setdefault(None, []).append(value)
    return {
        lob: Decimal(str(median(values))).quantize(Decimal("0.01"))
        for lob, values in by_lob.items()
    }


def tier_for(u: Decimal) -> str:
    if u >= Decimal("0.9"):
        return "T0"
    if u >= Decimal("0.5"):
        return "T1"
    return "T2"


def compute_score(
    snapshot: MemberSnapshot,
    signals: list[Signal],
    clock: Clock,
    medians: dict[str | None, Decimal],
    risk_override: RiskInput | None = None,
    handled: frozenset[tuple[str, tuple[int, ...]]] = frozenset(),
) -> ScoreResult:
    now = clock.now()
    fact_ids: set[int] = set()

    risk = risk_override or plan_risk(snapshot)
    if risk is None:
        lob = line_of_business(snapshot)
        risk = RiskInput(medians.get(lob, medians.get(None, Decimal("0"))), "cohort_median", None)
    elif risk.fact_id is not None:
        fact_ids.add(risk.fact_id)

    # U_deadline: earliest member-contact deadline (rules + open care gaps).
    deadlines: list[tuple[datetime, str, list[int]]] = [
        (s.due_at, s.rule_id, list(s.input_fact_ids))
        for s in signals
        if s.due_at is not None and s.deadline_kind == "member_contact"
    ]
    tz = member_tz(snapshot)
    for gap in open_care_gaps(snapshot):
        anchor = d(gap.value.get("anchor_date"))
        if gap.key in CONTACT_MEASURES and anchor and successful_contact_since(snapshot, anchor):
            continue  # a connected call after the discharge meets a contact-type deadline
        gap_due = d(gap.value.get("due_date"))
        if gap_due is not None:
            deadlines.append((due_at(gap_due, tz), f"care gap {gap.key}", [gap.id]))
    hours = deadline = source = None
    u_deadline = Decimal(0)
    if deadlines:
        deadline, source, ids = min(deadlines, key=lambda item: (item[0], item[1]))
        fact_ids.update(ids)
        hours = (Decimal(str((deadline - now).total_seconds())) / 3600).quantize(Decimal("0.01"))
        u_deadline = min(max(1 - hours / U_WINDOW_HOURS, Decimal(0)), Decimal(1))

    # Signals a person has acted on (a task exists) no longer drive clinical urgency.
    open_signals = [
        s for s in signals if (s.rule_id, tuple(sorted(s.input_fact_ids))) not in handled
    ]
    u_clinical = max((U_CLINICAL[s.severity] for s in open_signals), default=Decimal(0))
    u = max(u_deadline, u_clinical)

    # M: the best fixable lever, discounted when its key input is stale.
    m, lever, lever_date = Decimal(0), None, None
    today = now.astimezone(PLAN_TZ).date()
    for signal in signals:
        if not signal.lever:
            continue
        value = M_LEVER
        if signal.key_input_date is None or (today - signal.key_input_date).days > M_STALE_DAYS:
            value *= M_STALE_FACTOR
        if value > m:
            m, lever, lever_date = value, signal.rule_id, signal.key_input_date
            if signal.key_input_fact_id:
                fact_ids.add(signal.key_input_fact_id)

    # A: the best authorised contact that can actually be called.
    callable_contacts = policy.callable_contacts(snapshot.contacts)
    best = max(callable_contacts, key=lambda c: (c.confidence, c.number), default=None)
    a = Decimal(str(best.confidence)) if best else Decimal(0)
    if best:
        fact_ids.update(best.fact_ids)

    parts = {
        "R": WEIGHTS["R"] * risk.value,
        "U": WEIGHTS["U"] * u,
        "M": WEIGHTS["M"] * m,
        "A": WEIGHTS["A"] * a,
    }
    score = sum(parts.values(), Decimal(0)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    for signal in signals:
        fact_ids.update(signal.input_fact_ids)
    return ScoreResult(
        member_id=snapshot.member.member_id,
        r=risk,
        u=u,
        u_deadline=u_deadline,
        u_clinical=u_clinical,
        hours_to_deadline=hours,
        deadline_at=deadline,
        deadline_source=source,
        m=m,
        m_lever=lever,
        m_key_input_date=lever_date,
        a=a,
        a_contact=best.number if best else None,
        score=score,
        tier=tier_for(u),
        parts=parts,
        input_fact_ids=sorted(fact_ids),
        signals=signals,
    )


def rank(results: list[ScoreResult]) -> list[ScoreResult]:
    """Tier first (T0, T1, T2), then score descending."""
    return sorted(results, key=lambda r: (r.tier, -r.score, r.member_id))
