"""Draft a call note from the transcript, validate it, log it, and measure how it is used.

Rules-based pre-fill (app/encounters/template.py) remains the main documentation saving; this
draft only fills the free-text note. It is on for every pod in demo mode, and pod by pod in a
pilot while the major-edit rate (GET /admin/ai-draft/metrics) is watched.
"""

import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_draft import prompt
from app.ai_draft.client import DraftModel, DraftUnavailableError
from app.ai_draft.medications import known_terms
from app.ai_draft.models import LOG_STATUSES, AiDraft, AiGuardrailMetric, AiLog
from app.ai_draft.provenance import flatten, normalise
from app.ai_draft.transcript import load_transcript, render
from app.ai_draft.validate import check_draft, parse_output
from app.consent import policy
from app.core.clock import Clock
from app.core.config import Settings
from app.encounters.models import Encounter
from app.encounters.service import open_encounter
from app.facts.models import Fact
from app.workbench.actions import ActionError
from app.workbench.audit import audit
from app.workbench.models import User

FEATURE = "note_draft"
MAJOR_EDIT_THRESHOLD = 0.3
MIN_MATCH_CHARS = 20  # drafted sentences shorter than this are too generic to trace


def is_enabled(settings: Settings, user: User) -> bool:
    return settings.demo_mode or (user.pod is not None and user.pod in settings.ai_draft_pods)


@dataclass(frozen=True)
class DraftResult:
    available: bool
    reason: str | None
    draft: AiDraft | None
    log_id: int


def _medication_fact_text(session: Session, member_id: str) -> str:
    """Names from the member's visible medication Facts (masked Part 2 records stay out)."""
    names = []
    for fact in session.scalars(
        select(Fact).where(
            Fact.member_id == member_id,
            Fact.type == "medication",
            Fact.superseded_by.is_(None),
        )
    ):
        if policy.is_masked(fact):
            continue
        names += [fact.key, str(fact.value.get("product") or ""), str(fact.value.get("name") or "")]
    return " ".join(names)


def _require_ready(settings: Settings, user: User, encounter: Encounter) -> None:
    if not is_enabled(settings, user):
        raise ActionError(403, "the AI note draft is not switched on for your pod")
    if encounter.status != "open":
        raise ActionError(409, f"the AI draft is for live calls; this one is {encounter.status}")
    decision = policy.can_transcribe(encounter)
    if not decision:
        raise ActionError(409, decision.reason)


def generate(
    session: Session,
    user: User,
    encounter_id: int,
    clock: Clock,
    model: DraftModel,
    settings: Settings,
) -> DraftResult:
    encounter = open_encounter(session, encounter_id, user)
    _require_ready(settings, user, encounter)
    turns = load_transcript(settings.transcripts_dir, encounter.member_id)
    if not turns:
        raise ActionError(404, "no transcript is available for this call")

    user_prompt = prompt.user_message(turns)
    started = time.perf_counter()
    reply = None
    failure: DraftUnavailableError | None = None
    try:
        reply = model.complete(prompt.SYSTEM_PROMPT, user_prompt, prompt.OUTPUT_SCHEMA)
        raw = parse_output(reply.text)
    except DraftUnavailableError as exc:
        failure = exc
    except Exception as exc:  # never let the draft break the call: the nurse writes as normal
        failure = DraftUnavailableError("error", f"{type(exc).__name__}: {exc}")
    latency_ms = round((time.perf_counter() - started) * 1000)

    status = "ok"
    if failure is not None:
        status = failure.kind if failure.kind in LOG_STATUSES else "api_error"
    log = AiLog(
        encounter_id=encounter.id,
        created_at=clock.now(),
        actor=user.username,
        feature=FEATURE,
        model=reply.model if reply else model.name,
        prompt_version=prompt.PROMPT_VERSION,
        system_prompt=prompt.SYSTEM_PROMPT,
        user_prompt=user_prompt,
        output=reply.text if reply else None,
        status=status,
        error=str(failure) if failure else None,
        latency_ms=latency_ms,
        request_id=reply.request_id if reply else None,
        input_tokens=reply.input_tokens if reply else None,
        output_tokens=reply.output_tokens if reply else None,
    )
    session.add(log)
    session.flush()

    if failure is not None:
        audit(
            session,
            clock,
            actor=user.username,
            action="ai_draft_unavailable",
            object_type="encounter",
            object_id=encounter.id,
            member_id=encounter.member_id,
            detail={"ai_log_id": log.id, "kind": failure.kind},
        )
        return DraftResult(False, "AI draft unavailable", None, log.id)

    known = known_terms(render(turns), _medication_fact_text(session, encounter.member_id))
    checked = check_draft(raw, turns, known)
    draft = AiDraft(
        encounter_id=encounter.id,
        ai_log_id=log.id,
        created_at=clock.now(),
        created_by=user.username,
        content={
            "sentences": [asdict(s) for s in checked.sentences],
            "open_questions": list(checked.open_questions),
            "turns": [asdict(t) for t in turns],
        },
        note_text=checked.note_text,
        unsupported_count=checked.unsupported_count,
        blocked_count=checked.blocked_count,
        flagged_medications=checked.flagged_medications,
    )
    session.add(draft)
    session.flush()
    audit(
        session,
        clock,
        actor=user.username,
        action="ai_draft_generated",
        object_type="encounter",
        object_id=encounter.id,
        member_id=encounter.member_id,
        detail={
            "ai_log_id": log.id,
            "draft_id": draft.id,
            "unsupported": checked.unsupported_count,
            "blocked": checked.blocked_count,
            "flagged_medications": checked.flagged_medications,
        },
    )
    return DraftResult(True, None, draft, log.id)


def latest_draft(session: Session, encounter_id: int) -> AiDraft | None:
    return session.scalars(
        select(AiDraft).where(AiDraft.encounter_id == encounter_id).order_by(AiDraft.id.desc())
    ).first()


# --- write-back provenance --------------------------------------------------------------------


def _drafted_sentences(session: Session, encounter_id: int) -> list[str]:
    texts: list[str] = []
    for draft in session.scalars(select(AiDraft).where(AiDraft.encounter_id == encounter_id)):
        texts += [s["text"] for s in draft.content["sentences"]]
        texts += draft.content["open_questions"]
    drafted = (normalise(t) for t in texts)
    return [t for t in drafted if len(t) >= MIN_MATCH_CHARS]


def ai_sourced_fields(session: Session, encounter_id: int, values: dict[str, Any]) -> set[str]:
    """Our field ids whose stored value contains a sentence the AI drafted on this encounter.

    Values lose their AiDrafted type once stored, so at save time provenance is re-established
    by matching against the encounter's drafts. The mapping then refuses these fields unless
    they are the free-text note.
    """
    drafted = _drafted_sentences(session, encounter_id)
    if not drafted:
        return set()
    return {
        key
        for key, value in values.items()
        if any(sentence in normalise(flatten(value)) for sentence in drafted)
    }


# --- guardrail metrics ------------------------------------------------------------------------


def edit_distance(draft: str, saved: str) -> float:
    """Word-level Levenshtein distance, normalised by the longer text (0 same, 1 rewritten)."""
    a, b = normalise(draft).split(), normalise(saved).split()
    if not a and not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, word in enumerate(a, start=1):
        current = [i]
        for j, other in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other))
            )
        previous = current
    return previous[-1] / max(len(a), len(b))


def record_guardrails(
    session: Session, user: User, encounter: Encounter, clock: Clock
) -> AiGuardrailMetric | None:
    """Called when the nurse saves. One row per encounter, against the latest draft."""
    draft = latest_draft(session, encounter.id)
    if draft is None:
        return None
    existing = session.scalars(
        select(AiGuardrailMetric).where(AiGuardrailMetric.encounter_id == encounter.id)
    ).first()
    if existing is not None:
        return existing
    now = clock.now()
    distance = edit_distance(draft.note_text, encounter.notes or "")
    metric = AiGuardrailMetric(
        encounter_id=encounter.id,
        draft_id=draft.id,
        pod=user.pod,
        unsupported_count=draft.unsupported_count,
        edit_distance=round(distance, 4),
        major_edit=distance > MAJOR_EDIT_THRESHOLD,
        seconds_to_save=max(0, round((now - draft.created_at).total_seconds())),
        saved_at=now,
    )
    session.add(metric)
    session.flush()
    return metric


def metrics_by_pod(session: Session) -> list[dict[str, Any]]:
    rows = list(session.scalars(select(AiGuardrailMetric).order_by(AiGuardrailMetric.id)))
    pods = sorted({r.pod or "UNKNOWN" for r in rows})
    out = []
    for pod in pods:
        mine = [r for r in rows if (r.pod or "UNKNOWN") == pod]
        out.append(
            {
                "pod": pod,
                "encounters": len(mine),
                "major_edits": sum(r.major_edit for r in mine),
                "major_edit_ratio": round(sum(r.major_edit for r in mine) / len(mine), 3),
                "unsupported_sentences": sum(r.unsupported_count for r in mine),
                "median_seconds_to_save": statistics.median(r.seconds_to_save for r in mine),
            }
        )
    return out
