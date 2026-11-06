"""Demo-mode state, kept in a small JSON file so every process (API, worker) sees the same
frozen clock and the same operator toggles. Only read when DEMO_MODE=true."""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.core.config import Settings

PAUSABLE_FEEDS = ("pharmacy", "adt")


@dataclass
class DemoState:
    instant: datetime = REFERENCE_INSTANT
    applied_steps: list[str] = field(default_factory=list)
    paused_feeds: list[str] = field(default_factory=list)
    # Feeds with a delivery waiting because the feed was paused when it arrived.
    held_feeds: list[str] = field(default_factory=list)
    ai_timeout: bool = False
    # Rows added on top of the synthetic snapshot, per feed (scripted fills, injected rows).
    extra_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # "expire" / "restore" events applied to Kayla's Part 2 consent, in order.
    consent_events: list[str] = field(default_factory=list)
    deliveries: int = 0

    def to_json(self) -> str:
        data = asdict(self)
        data["instant"] = self.instant.isoformat()
        return json.dumps(data, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "DemoState":
        data = json.loads(text)
        data["instant"] = datetime.fromisoformat(data["instant"])
        return cls(**data)


def load_state(settings: Settings) -> DemoState:
    path = settings.demo_state_file
    if not path.is_file():
        return DemoState()
    return DemoState.from_json(path.read_text(encoding="utf-8"))


def save_state(settings: Settings, state: DemoState) -> None:
    path = settings.demo_state_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.to_json(), encoding="utf-8")


def demo_clock(settings: Settings) -> FixedClock:
    return FixedClock(load_state(settings).instant)


def paused_feeds(settings: Settings) -> list[str]:
    return load_state(settings).paused_feeds if settings.demo_mode else []
