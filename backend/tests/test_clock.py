from datetime import datetime, timedelta

import pytest

from app.core import clock as clock_module
from app.core.clock import REFERENCE_INSTANT, FixedClock, SystemClock, get_clock
from app.core.config import Settings


def test_reference_instant_is_0800_eastern_standard_time() -> None:
    assert REFERENCE_INSTANT.isoformat() == "2026-11-09T08:00:00-05:00"


def test_fixed_clock_defaults_to_reference_instant() -> None:
    assert FixedClock().now() == REFERENCE_INSTANT


def test_fixed_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 11, 9, 8, 0))  # noqa: DTZ001


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().utcoffset() is not None


def test_get_clock_follows_clock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock_module, "get_settings", lambda: Settings(clock_mode="fixed"))
    assert get_clock().now() == REFERENCE_INSTANT

    monkeypatch.setattr(clock_module, "get_settings", lambda: Settings(clock_mode="system"))
    assert abs(get_clock().now() - SystemClock().now()) < timedelta(minutes=1)


def test_business_logic_never_reads_the_wall_clock() -> None:
    """CLAUDE.md: the Clock is injected. Ruff (TID251) enforces this at lint time; this test
    enforces it in `make test` too. Only app/core/clock.py may read the wall clock."""
    import re
    from pathlib import Path

    wall = re.compile(r"\b(datetime\.(now|utcnow|today)|date\.today)\(|\btime\.time\(\)")
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = [
        f"{path.relative_to(app_dir)}:{number}"
        for path in app_dir.rglob("*.py")
        if path.name != "clock.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if wall.search(line)
    ]
    assert offenders == []
