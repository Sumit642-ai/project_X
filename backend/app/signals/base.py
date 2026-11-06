from dataclasses import dataclass
from datetime import date, datetime
from typing import ClassVar, Literal

from app.core.clock import Clock
from app.facts.models import Fact
from app.facts.snapshot import MemberSnapshot
from app.signals.calendar import BusinessCalendar, default_calendar

Severity = Literal["red", "amber", "info"]
DeadlineKind = Literal["member_contact", "um", "appeal"]
MAX_INSIGHT_WORDS = 12


@dataclass(frozen=True)
class Signal:
    member_id: str
    rule_id: str
    rule_version: str
    input_fact_ids: tuple[int, ...]
    insight_text: str
    severity: Severity
    suggested_step: str
    due_at: datetime | None = None  # UTC
    due_tz: str | None = None
    deadline_kind: DeadlineKind | None = None
    lever: bool = False
    key_input_fact_id: int | None = None
    key_input_date: date | None = None

    def __post_init__(self) -> None:
        words = len(self.insight_text.split())
        if words > MAX_INSIGHT_WORDS:
            raise ValueError(f"{self.rule_id}: insight has {words} words (max 12)")
        if not self.input_fact_ids:
            raise ValueError(f"{self.rule_id}: a signal must cite its input facts")
        if self.due_at is not None and (self.due_at.utcoffset() is None or self.due_tz is None):
            raise ValueError(f"{self.rule_id}: deadlines need a UTC instant and a time zone")


class Rule:
    rule_id: ClassVar[str]
    version: ClassVar[str] = "1.0.0"
    owner: ClassVar[str] = "clinical-ops"
    severity: ClassVar[Severity]
    description: ClassVar[str]
    # A lever is something the case manager can fix (feeds M in the score).
    lever: ClassVar[bool] = False
    deadline_kind: ClassVar[DeadlineKind | None] = None

    def __init__(self, calendar: BusinessCalendar | None = None) -> None:
        self.calendar = calendar or default_calendar()

    def evaluate(self, snapshot: MemberSnapshot, clock: Clock) -> list[Signal]:
        raise NotImplementedError

    def signal(
        self,
        snapshot: MemberSnapshot,
        *,
        inputs: list[Fact],
        insight: str,
        step: str,
        due: datetime | None = None,
        tz: str | None = None,
        key_input: Fact | None = None,
        severity: Severity | None = None,
    ) -> Signal:
        return Signal(
            member_id=snapshot.member.member_id,
            rule_id=self.rule_id,
            rule_version=self.version,
            input_fact_ids=tuple(sorted({f.id for f in inputs})),
            insight_text=insight,
            severity=severity or self.severity,
            suggested_step=step,
            due_at=due,
            due_tz=tz if due is not None else None,
            deadline_kind=self.deadline_kind if due is not None else None,
            lever=self.lever,
            key_input_fact_id=key_input.id if key_input else None,
            key_input_date=key_input.event_date if key_input else None,
        )
