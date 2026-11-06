"""Demo mode routes (404 unless DEMO_MODE=true), plus the data layer's unmapped-code report."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DbSession, require_role
from app.core.config import Settings, get_settings
from app.datalayer_mock.ingest.models import Load
from app.datalayer_mock.normalise.models import UnmappedCode
from app.demo import service
from app.demo.state import load_state
from app.workbench.audit import audit
from app.workbench.models import User
from app.workbench.seed import SEED_USERS, SIGN_IN_LABELS
from app.writeback.client import CmClient, get_cm_client

router = APIRouter(tags=["demo"])
Staff = Annotated[User, Depends(require_role("cm", "supervisor", "call_agent"))]
Supervisor = Annotated[User, Depends(require_role("supervisor"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Cm = Annotated[CmClient, Depends(get_cm_client)]


class SignInUser(BaseModel):
    username: str
    label: str


class DemoConfig(BaseModel):
    demo_mode: bool
    users: list[SignInUser]


@router.get("/demo/config")
def demo_config(settings: SettingsDep) -> DemoConfig:
    """Public. In demo mode the sign-in page lists the seeded users; otherwise it lists none."""
    users = (
        [SignInUser(username=u.username, label=SIGN_IN_LABELS[u.username]) for u in SEED_USERS]
        if settings.demo_mode
        else []
    )
    return DemoConfig(demo_mode=settings.demo_mode, users=users)


def _done(
    session: DbSession, settings: Settings, user: User, action: str, detail: dict[str, Any]
) -> None:
    audit(
        session,
        service._clock(load_state(settings)),
        actor=user.username,
        action=f"demo_{action}",
        object_type="demo",
        object_id=action,
        detail=detail,
    )
    session.commit()


@router.get("/demo/state")
def demo_state(session: DbSession, settings: SettingsDep, user: Staff, cm: Cm) -> dict[str, Any]:
    service.require_demo(settings)
    return service.status(session, settings, cm)


@router.post("/demo/clock/advance/{step_id}")
def advance_clock(
    step_id: str, session: DbSession, settings: SettingsDep, user: Staff
) -> dict[str, Any]:
    """Move the frozen clock forward; scripted feed files for the steps passed are loaded."""
    service.require_demo(settings)
    result = service.advance(session, settings, step_id)
    _done(session, settings, user, "advance_clock", {"step": step_id, **result})
    return result


@router.post("/demo/clock/reset")
def reset_demo(session: DbSession, settings: SettingsDep, user: Staff, cm: Cm) -> dict[str, str]:
    """Back to how `make demo` left it (pristine database, Monday 08:00, CM platform empty)."""
    service.require_demo(settings)
    service.reset(session, settings, cm)
    return {"instant": load_state(settings).instant.isoformat()}


@router.post("/demo/feeds/{feed}/{action}")
def feed_toggle(
    feed: str,
    action: Literal["pause", "resume"],
    session: DbSession,
    settings: SettingsDep,
    user: Staff,
) -> dict[str, Any]:
    service.require_demo(settings)
    resolved = service.set_feed_paused(session, settings, feed, action == "pause")
    _done(session, settings, user, f"{action}_{feed}", {"resolved_tasks": resolved})
    return {"feed": feed, "paused": action == "pause", "resolved_tasks": resolved}


@router.post("/demo/cm/{action}")
def cm_toggle(
    action: Literal["down", "up", "conflict"],
    session: DbSession,
    settings: SettingsDep,
    user: Staff,
    cm: Cm,
) -> dict[str, Any]:
    service.require_demo(settings)
    if action == "conflict":
        result = service.cm_conflict(cm)
    else:
        result = service.set_cm(session, settings, cm, up=action == "up")
    _done(session, settings, user, f"cm_{action}", result)
    return result


@router.post("/demo/inject/{what}")
def inject(
    what: Literal["bad-pharmacy-file", "unknown-ndc"],
    session: DbSession,
    settings: SettingsDep,
    user: Staff,
) -> dict[str, Any]:
    service.require_demo(settings)
    load: Load | None
    if what == "bad-pharmacy-file":
        load = service.inject_bad_pharmacy_file(session, settings)
    else:
        load = service.inject_unknown_ndc(session, settings)
    result = (
        {"load_id": load.id, "status": load.status, "error": load.error}
        if load
        else {"held": "pharmacy feed is paused; the file arrives when it resumes"}
    )
    _done(session, settings, user, what.replace("-", "_"), result)
    return result


@router.post("/demo/ai-timeout/{state}")
def ai_timeout(
    state: Literal["on", "off"], session: DbSession, settings: SettingsDep, user: Staff
) -> dict[str, bool]:
    service.require_demo(settings)
    service.set_ai_timeout(settings, state == "on")
    _done(session, settings, user, f"ai_timeout_{state}", {})
    return {"ai_timeout": state == "on"}


@router.post("/demo/consent/kayla-part2/{event}")
def kayla_consent(
    event: Literal["expire", "restore"], session: DbSession, settings: SettingsDep, user: Staff
) -> dict[str, Any]:
    service.require_demo(settings)
    load = service.kayla_consent(session, settings, event)
    result = {"event": event, "load_id": load.id if load else None}
    _done(session, settings, user, f"kayla_consent_{event}", result)
    return result


@router.get("/admin/unmapped-codes")
def unmapped_codes(session: DbSession, user: Supervisor) -> list[dict[str, Any]]:
    """Codes the terminology tables could not map, as reported by the data layer."""
    return [
        {
            "code_system": u.code_system,
            "code": u.code,
            "display": u.display,
            "source_stream": u.source_stream,
            "occurrences": u.occurrences,
            "first_load_id": u.first_load_id,
        }
        for u in session.scalars(select(UnmappedCode).order_by(UnmappedCode.id))
    ]
