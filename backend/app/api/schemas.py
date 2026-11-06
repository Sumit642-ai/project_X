from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str


class UserOut(Out):
    username: str
    name: str
    role: str
    credential: str | None
    program: str | None
    licensed_states: list[str]
    languages: list[str]


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


# --- shared -----------------------------------------------------------------------------------


class UnknownOut(BaseModel):
    value: Literal["UNKNOWN"] = "UNKNOWN"
    type: str
    key: str | None = None
    reason: str
    as_of: date | None = None


# --- queue ------------------------------------------------------------------------------------


class NextBestAction(BaseModel):
    """Next best action (suggested): the step a rule suggests, with the reason it fired."""

    text: str
    reason: str
    rule_id: str


class DuplicateFlag(BaseModel):
    flagged: bool
    label: str | None = None
    link_ids: list[int] = Field(default_factory=list)


class ScoreInputs(BaseModel):
    r: Decimal
    u: Decimal
    m: Decimal
    a: Decimal


class QueueRow(BaseModel):
    rank: int
    member_id: str
    name: str
    lob: str | None
    age: int | None
    score_inputs: ScoreInputs
    tier: str
    score: Decimal
    why: list[str]
    due_at: datetime | None
    due_tz: str | None
    next_best_action: NextBestAction | None = Field(
        title="Next best action (suggested)",
        description='Shown to users as "Next best action (suggested)"; never a decision.',
    )
    duplicate: DuplicateFlag
    assigned_cm: str | None


class StaleFeed(BaseModel):
    feed: str
    stream: str
    reason: str


class Capacity(BaseModel):
    active: int
    target: int | None


class QueueHeader(BaseModel):
    now: datetime  # the server Clock; the UI measures due times against this
    data_as_of: datetime | None
    scored_on: date | None
    stale_feeds: list[StaleFeed]
    tier_counts: dict[str, int]
    capacity: Capacity | None


class QueueOut(BaseModel):
    header: QueueHeader
    rows: list[QueueRow]


class ReassignRequest(BaseModel):
    member_id: str
    to_cm: str
    override_reason: str | None = Field(default=None, min_length=5)


class AssignmentOut(Out):
    member_id: str
    cm_username: str
    status: str
    assigned_by: str
    assigned_at: datetime
    reason: str | None


# --- explain ----------------------------------------------------------------------------------


class ExplainOut(BaseModel):
    member_id: str
    explanation: str
    tier: str
    r: Decimal
    r_source: str
    verify: bool
    u: Decimal
    u_deadline: Decimal
    u_clinical: Decimal
    hours_to_deadline: Decimal | None
    deadline_source: str | None
    m: Decimal
    m_lever: str | None
    a: Decimal
    a_contact: str | None
    input_fact_ids: list[int]


# --- 360 --------------------------------------------------------------------------------------


class FactOut(BaseModel):
    id: int
    type: str
    key: str
    value: dict[str, Any]
    event_date: date | None
    loaded_at: datetime
    source_system: str
    source_record_id: str
    status: str
    confidence: Decimal
    freshness: str
    masked: bool


class SignalOut(BaseModel):
    rule_id: str
    severity: str
    insight_text: str
    suggested_step: str
    due_at: datetime | None
    input_fact_ids: list[int]


class SinceLastContact(BaseModel):
    reference: str
    since: datetime | None
    facts: list[FactOut]
    signals: list[SignalOut]


class ConflictOut(BaseModel):
    label: str = "flagged by data layer"
    id: int
    fact_type: str
    key: str
    kind: str
    summary: str
    status: str
    fact_ids: list[int]
    detected_at: datetime


class ContactOut(BaseModel):
    number: str
    owner: str
    owner_name: str | None
    relationship: str | None
    source: str | None
    last_verified: date | None
    last_outcome: str | None
    best_window: str | None
    confidence: Decimal
    consent_sms: bool
    authorised: bool
    callable: bool
    not_callable_reason: str | None


class CareTeamMember(BaseModel):
    role: str
    name: str | UnknownOut
    detail: str | None = None


class DocumentOut(BaseModel):
    id: int
    type: str
    facility: str | None
    status: str
    requested_at: datetime | None
    received_at: datetime | None


class ConsentOut(BaseModel):
    id: int
    type: str
    party: str | None
    phone: str | None
    program: str | None
    scope: str | None
    valid_from: date
    valid_to: date | None
    valid: bool


class RiskOut(BaseModel):
    value: Decimal | UnknownOut
    basis: str  # plan | cohort_median
    verify: bool
    model: str | None
    scored_at: date | None


class PendingLinkOut(BaseModel):
    id: int
    source_system: str
    source_record_id: str
    confidence: Decimal
    status: str
    label: str = "flagged by data layer"


class MemberHeader(BaseModel):
    member_id: str
    name: str
    dob: date
    age: int
    lob: str | None
    plan: str | None
    language: str | None
    proxy_language: str | None
    assigned_cm: str | None


class Member360(BaseModel):
    now: datetime
    claims_as_of: date | None
    member: MemberHeader
    since_last_contact: SinceLastContact
    last_call_note: UnknownOut
    member_goal: UnknownOut
    conflicts: list[ConflictOut]
    contacts: list[ContactOut]
    care_team: list[CareTeamMember]
    documents: list[DocumentOut]
    consents: list[ConsentOut]
    facts: list[FactOut]
    unknowns: list[UnknownOut]
    risk: RiskOut
    pending_links: list[PendingLinkOut]
    # ADT is late or paused: discharges may be missing, so the nurse can record one by hand.
    adt_feed_stale: bool = False


class DischargeRequest(BaseModel):
    facility: str = Field(min_length=2)
    discharge_at: datetime
    note: str | None = None


# --- actions ----------------------------------------------------------------------------------


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=5)


class Part2NoteOut(BaseModel):
    fact_id: int
    service_date: date | None
    program: str | None
    note_type: str | None
    counselor: str | None
    note_text: str | None


class Part2RevealOut(BaseModel):
    member_id: str
    consent_id: int
    audit_event_id: int
    notes: list[Part2NoteOut]
    redisclosure_notice: str


class MemberReportRequest(BaseModel):
    value: str = Field(min_length=1)


class FactCreatedOut(BaseModel):
    fact_id: int
    conflict_id: int
    conflict_status: str


class LinkDecisionOut(BaseModel):
    link_id: int
    status: str
    decided_by: str | None
    decided_at: datetime | None


class FeedStatusOut(BaseModel):
    feed: str
    stream: str
    last_good_load_at: datetime | None
    age_hours: float | None
    data_as_of: date | None
    stale: bool
    reason: str | None


class SnoozeRequest(BaseModel):
    reason: str = Field(min_length=5)
    until: date


class SnoozeOut(Out):
    member_id: str
    cm_username: str
    until: date
    reason: str


class NotNowRequest(BaseModel):
    reason: str = Field(min_length=5)
    rule_id: str | None = None


class AckOut(BaseModel):
    ok: bool = True
    audit_event_id: int
