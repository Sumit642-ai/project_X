from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings

STATE_TZ = {"OH": "America/New_York"}
DEFAULT_TZ = "America/New_York"
DUE_TIME = time(17, 0)  # deadlines fall at 17:00 local on the due day


class BusinessCalendar:
    """Weekdays minus a configurable holiday list."""

    def __init__(self, holidays: Iterable[date]) -> None:
        self.holidays = frozenset(holidays)

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def add_business_days(self, start: date, days: int) -> date:
        current = start
        remaining = days
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_business_day(current):
                remaining -= 1
        return current


def default_calendar() -> BusinessCalendar:
    return BusinessCalendar(get_settings().business_holidays)


def due_at(day: date, tz_name: str) -> datetime:
    """17:00 local on `day`, returned in UTC (store this; keep tz_name alongside)."""
    return datetime.combine(day, DUE_TIME, tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def timezone_for_state(state: str | None) -> str:
    return STATE_TZ.get(state or "", DEFAULT_TZ)
