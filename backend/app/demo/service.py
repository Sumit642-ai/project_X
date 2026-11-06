"""Demo operations behind the clock controls and the /demo-admin operator panel."""

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, FixedClock
from app.core.config import Settings
from app.datalayer_mock.ingest import ingest_file
from app.datalayer_mock.ingest.models import Load
from app.datalayer_mock.normalise.models import UnmappedCode
from app.demo.build import copy_sqlite, sqlite_path
from app.demo.deliveries import (
    UNKNOWN_NDC_ROW,
    bad_pharmacy_file,
    deliver,
    demo_landing,
    intraday_steps,
    refresh_downstream,
)
from app.demo.state import PAUSABLE_FEEDS, DemoState, load_state, save_state
from app.workbench.actions import ActionError
from app.writeback.client import CmClient
from app.writeback.service import sync_due

CONFLICT_MEMBER = "SYN-001"


def require_demo(settings: Settings) -> None:
    if not settings.demo_mode:
        raise ActionError(404, "demo mode is off (DEMO_MODE=true turns it on)")


def _clock(state: DemoState) -> FixedClock:
    return FixedClock(state.instant)


# --- clock ------------------------------------------------------------------------------------


def advance(session: Session, settings: Settings, step_id: str) -> dict[str, Any]:
    """Move the frozen clock to a scripted step, delivering every step passed on the way."""
    state = load_state(settings)
    steps = intraday_steps()
    target = next((s for s in steps if s.id == step_id), None)
    if target is None:
        raise ActionError(404, f"no demo step {step_id}")
    target_at = datetime.fromisoformat(target.at)
    if target_at <= state.instant:
        raise ActionError(409, f"the demo clock is already at or past {target.label}")
    resolved: list[int] = []
    for step in steps:
        at = datetime.fromisoformat(step.at)
        if step.id in state.applied_steps or at > target_at:
            continue
        state.instant = at
        clock = _clock(state)
        for delivery in step.deliveries:
            feed = delivery["feed"]
            state.extra_rows.setdefault(feed, []).extend(delivery["rows"])
            deliver(session, settings, state, feed, clock)
        resolved += refresh_downstream(session, clock)
        state.applied_steps.append(step.id)
    state.instant = target_at
    save_state(settings, state)
    return {"instant": state.instant.isoformat(), "resolved_tasks": resolved}


def _force_remove(function: Any, path: str, _exc: Any) -> None:
    os.chmod(path, stat.S_IWRITE)  # the landing area is read-only by design
    function(path)


def reset(session: Session, settings: Settings, cm: CmClient) -> None:
    """Back to the state `make demo` left: pristine database, 08:00 Monday, CM up and empty."""
    pristine = settings.demo_pristine_db
    if not pristine.is_file():
        raise ActionError(409, "no pristine copy of the demo database: run make demo")
    bind = session.get_bind()
    session.close()
    if isinstance(bind, Engine):
        bind.dispose()  # no pooled connection may hold the old pages
    copy_sqlite(pristine, sqlite_path(settings.database_url))
    if settings.demo_inbox_dir.exists():
        shutil.rmtree(settings.demo_inbox_dir, onerror=_force_remove)
    save_state(settings, DemoState())
    cm.http.post("/admin/reset")


# --- feeds ------------------------------------------------------------------------------------


def set_feed_paused(session: Session, settings: Settings, feed: str, paused: bool) -> list[int]:
    if feed not in PAUSABLE_FEEDS:
        raise ActionError(404, f"{feed} cannot be paused in the demo")
    state = load_state(settings)
    resolved: list[int] = []
    if paused and feed not in state.paused_feeds:
        state.paused_feeds.append(feed)
    elif not paused and feed in state.paused_feeds:
        state.paused_feeds.remove(feed)
        if feed in state.held_feeds:  # deliveries that waited arrive now
            state.held_feeds.remove(feed)
            deliver(session, settings, state, feed, _clock(state))
            resolved = refresh_downstream(session, _clock(state))
    save_state(settings, state)
    return resolved


def inject_bad_pharmacy_file(session: Session, settings: Settings) -> Load:
    state = load_state(settings)
    clock = _clock(state)
    path = bad_pharmacy_file(settings, state, clock.now().astimezone(PLAN_TZ).date())
    load = ingest_file(session, path, clock=clock, landing_root=demo_landing(settings))
    save_state(settings, state)
    return load


def inject_unknown_ndc(session: Session, settings: Settings) -> Load | None:
    state = load_state(settings)
    rows = state.extra_rows.setdefault("pharmacy", [])
    if UNKNOWN_NDC_ROW not in rows:
        rows.append(UNKNOWN_NDC_ROW)
    load = deliver(session, settings, state, "pharmacy", _clock(state))
    if load is not None:
        refresh_downstream(session, _clock(state))
    save_state(settings, state)
    return load


# --- consent ----------------------------------------------------------------------------------


def kayla_consent(session: Session, settings: Settings, event: str) -> Load | None:
    """expire: Kayla's Part 2 consent lapsed yesterday. restore: she signed a new one today.
    Both arrive as CM-platform consent snapshots, so the policy sees them like real data."""
    state = load_state(settings)
    current = state.consent_events[-1] if state.consent_events else "restore"
    if event == current:
        raise ActionError(409, f"Kayla's Part 2 consent is already {_consent_word(current)}")
    state.consent_events.append(event)
    load = deliver(session, settings, state, "consents", _clock(state))
    refresh_downstream(session, _clock(state))
    save_state(settings, state)
    return load


def _consent_word(event: str) -> str:
    return "expired" if event == "expire" else "valid"


# --- mock CM platform -------------------------------------------------------------------------


def set_cm(session: Session, settings: Settings, cm: CmClient, up: bool) -> dict[str, Any]:
    cm.http.post("/admin/mode", json={"mode": "up" if up else "down"})
    synced: list[int] = []
    if up:  # the platform is back: send what waited, once
        synced = sync_due(session, _clock(load_state(settings)), cm, now_all=True).synced
    return {"mode": "up" if up else "down", "synced": synced}


def cm_conflict(cm: CmClient, member_id: str = CONFLICT_MEMBER) -> dict[str, Any]:
    response = cm.http.post(f"/admin/touch/{member_id}")
    result: dict[str, Any] = response.json()
    return result


def cm_mode(cm: CmClient) -> str:
    try:
        return str(cm.http.get("/health").json().get("mode", "unknown"))
    except Exception:  # the operator panel must render even if the mock is not running
        return "unreachable"


def set_ai_timeout(settings: Settings, on: bool) -> None:
    state = load_state(settings)
    state.ai_timeout = on
    save_state(settings, state)


# --- status -----------------------------------------------------------------------------------


def status(session: Session, settings: Settings, cm: CmClient) -> dict[str, Any]:
    state = load_state(settings)
    loads = list(session.scalars(select(Load).order_by(Load.id.desc()).limit(6)))
    unmapped = list(session.scalars(select(UnmappedCode).order_by(UnmappedCode.id)))
    return {
        "instant": state.instant.isoformat(),
        "steps": [
            {
                "id": s.id,
                "label": s.label,
                "story": s.story,
                "at": s.at,
                "applied": s.id in state.applied_steps,
                "available": datetime.fromisoformat(s.at) > state.instant,
            }
            for s in intraday_steps()
        ],
        "paused_feeds": state.paused_feeds,
        "held_feeds": state.held_feeds,
        "ai_timeout": state.ai_timeout,
        "kayla_part2_consent": _consent_word(
            state.consent_events[-1] if state.consent_events else "restore"
        ),
        "cm_mode": cm_mode(cm),
        "recent_loads": [
            {
                "id": load.id,
                "file": load.file,
                "status": load.status,
                "active": load.is_active,
                "error": load.error,
            }
            for load in loads
        ],
        "unmapped_codes": [
            {
                "code_system": u.code_system,
                "code": u.code,
                "display": u.display,
                "source_stream": u.source_stream,
                "occurrences": u.occurrences,
            }
            for u in unmapped
        ],
    }


def landing_files(settings: Settings) -> list[Path]:
    root = settings.demo_inbox_dir
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []
