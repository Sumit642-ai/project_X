from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.ai_draft import service
from app.ai_draft.client import DraftModel, get_draft_model
from app.ai_draft.models import AiDraft
from app.api.deps import ClockDep, DbSession, require_role
from app.core.config import Settings, get_settings
from app.encounters.service import open_encounter
from app.workbench.models import User

router = APIRouter(tags=["ai-draft"])
CaseManager = Annotated[User, Depends(require_role("cm"))]
Supervisor = Annotated[User, Depends(require_role("supervisor"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Model = Annotated[DraftModel, Depends(get_draft_model)]


class SentenceOut(BaseModel):
    section: Literal["summary", "note"]
    text: str
    source_turns: list[int]
    status: Literal["supported", "unsupported", "blocked"]
    reasons: list[str]
    flagged_medications: list[str]


class TurnOut(BaseModel):
    number: int
    speaker: str
    text: str


class DraftOut(BaseModel):
    id: int
    sentences: list[SentenceOut]
    open_questions: list[str]
    flagged_medications: list[str]
    unsupported_count: int
    blocked_count: int
    note_text: str
    turns: list[TurnOut]


class DraftResponse(BaseModel):
    enabled: bool
    available: bool
    reason: str | None = None
    draft: DraftOut | None = None


def _draft_out(draft: AiDraft) -> DraftOut:
    return DraftOut(
        id=draft.id,
        sentences=[SentenceOut(**s) for s in draft.content["sentences"]],
        open_questions=draft.content["open_questions"],
        flagged_medications=draft.flagged_medications,
        unsupported_count=draft.unsupported_count,
        blocked_count=draft.blocked_count,
        note_text=draft.note_text,
        turns=[TurnOut(**t) for t in draft.content["turns"]],
    )


@router.get("/encounters/{encounter_id}/ai-draft")
def get_draft(
    encounter_id: int, session: DbSession, user: CaseManager, settings: SettingsDep
) -> DraftResponse:
    """Whether the draft is on for this nurse's pod, and the latest draft for the call, if any."""
    open_encounter(session, encounter_id, user)
    if not service.is_enabled(settings, user):
        return DraftResponse(enabled=False, available=False, reason="not switched on for your pod")
    draft = service.latest_draft(session, encounter_id)
    return DraftResponse(
        enabled=True, available=draft is not None, draft=_draft_out(draft) if draft else None
    )


@router.post("/encounters/{encounter_id}/ai-draft")
def create_draft(
    encounter_id: int,
    session: DbSession,
    clock: ClockDep,
    user: CaseManager,
    settings: SettingsDep,
    model: Model,
) -> DraftResponse:
    """Draft the note from the call transcript. A model failure is not an error for the call:
    the response says the draft is unavailable and the nurse writes the note as normal."""
    result = service.generate(session, user, encounter_id, clock, model, settings)
    session.commit()
    return DraftResponse(
        enabled=True,
        available=result.available,
        reason=result.reason,
        draft=_draft_out(result.draft) if result.draft else None,
    )


@router.get("/admin/ai-draft/metrics")
def guardrail_metrics(session: DbSession, user: Supervisor) -> list[dict[str, Any]]:
    """Per pod: encounters saved with a draft, major-edit ratio, unsupported sentences, time to
    save. A pod's pilot continues only while its major-edit ratio stays low."""
    return service.metrics_by_pod(session)
