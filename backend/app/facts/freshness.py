"""How current a Fact is, by kind (annex Sheet 9). Display only: scores never read it.

- Screens (sdoh) are re-done about yearly: green under 6 months, amber 6-8, red from 9
  (months rounded, as the annex states them: an HRA from 4 Mar is "amber (8 months)").
- An open care gap with a deadline still ahead is current, whatever its anchor date.
- Services (aide hours, transport, home health) change monthly: green to 60 days, amber to 90.
- Everything else (fills, events, labs): green under 7 days, amber 7-30, red after 30.
- Grey: never received, or undated.
"""

from datetime import date
from typing import Any, Literal

from app.core.clock import PLAN_TZ, Clock
from app.facts.models import Fact
from app.facts.unknown import Unknown

Freshness = Literal["green", "amber", "red", "grey"]
DAYS_PER_MONTH = 30.44


def age_days(fact: Fact, clock: Clock) -> int | None:
    """Age from event_date (when it happened), not loaded_at (when we received it)."""
    if fact.event_date is None:
        return None
    return (clock.now().astimezone(PLAN_TZ).date() - fact.event_date).days


def _open_gap_ahead(fact: Any, today: date) -> bool:
    value = getattr(fact, "value", None) or {}
    due = value.get("due_date")
    if value.get("status") != "open" or not isinstance(due, str) or not due:
        return False
    return date.fromisoformat(due[:10]) >= today


def freshness(fact: Fact | Unknown | None, clock: Clock) -> Freshness:
    if fact is None or isinstance(fact, Unknown):
        return "grey"
    age = age_days(fact, clock)
    if age is None:
        return "grey"
    kind = getattr(fact, "type", None)
    if kind == "care_gap" and _open_gap_ahead(fact, clock.now().astimezone(PLAN_TZ).date()):
        return "green"
    if kind == "sdoh":
        months = round(age / DAYS_PER_MONTH)
        return "green" if months < 6 else "amber" if months < 9 else "red"
    if kind == "service":
        return "green" if age <= 60 else "amber" if age <= 90 else "red"
    if age < 7:
        return "green"
    if age <= 30:
        return "amber"
    return "red"
