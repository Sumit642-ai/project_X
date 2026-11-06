"""Clock service.

Business logic must never read the wall clock directly; it receives a Clock.
This module is the only place allowed to call datetime.now() (enforced by ruff TID251).
"""

from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.core.config import get_settings

PLAN_TZ = ZoneInfo("America/New_York")

# Reference clock for tests and demo: 2026-11-09T08:00 America/New_York.
REFERENCE_INSTANT = datetime(2026, 11, 9, 8, 0, tzinfo=PLAN_TZ)


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as a timezone-aware datetime."""
        ...


class FixedClock:
    def __init__(self, instant: datetime = REFERENCE_INSTANT) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class SystemClock:
    def __init__(self, tz: ZoneInfo = PLAN_TZ) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)


def get_clock() -> Clock:
    """FastAPI dependency; override in tests with app.dependency_overrides.

    In demo mode the frozen instant comes from the demo state, so the operator can move it.
    """
    settings = get_settings()
    if settings.clock_mode == "system":
        return SystemClock()
    if settings.demo_mode:
        from app.demo.state import demo_clock  # demo only; imported late to avoid a cycle

        return demo_clock(settings)
    return FixedClock()
