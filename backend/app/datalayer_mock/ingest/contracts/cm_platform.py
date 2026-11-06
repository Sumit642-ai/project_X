from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.datalayer_mock.ingest.contracts.base import (
    AwareDatetime,
    Contract,
    Phone,
    StreamContract,
    SynId,
)


class ConsentRecord(Contract):
    consent_id: SynId
    member_id: SynId
    consent_type: Literal["tcpa_sms", "part2", "personal_representative", "third_party_release"]
    phone: Phone | None
    program: str | None
    scope: str | None
    representative_name: str | None
    relationship: str | None
    recipient: str | None
    granted_date: date
    expires_date: date | None
    revoked_date: date | None
    source: str | None

    @model_validator(mode="after")
    def _type_specific_fields(self) -> Self:
        required = {
            "tcpa_sms": ("phone",),  # TCPA consent is per number
            "part2": ("program",),
            "personal_representative": ("representative_name",),
            "third_party_release": ("recipient",),
        }[self.consent_type]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.consent_type} consent requires {', '.join(missing)}")
        return self


class ContactPointRecord(Contract):
    contact_id: SynId
    member_id: SynId
    phone: Phone
    owner_type: Literal["member", "representative", "family", "facility"]
    owner_name: str | None
    relationship: str | None
    source: str | None
    last_verified: date | None
    last_outcome: (
        Literal[
            "answered",
            "answered_pharmacy_ivr",
            "no_answer",
            "voicemail",
            "disconnected",
            "not_tried",
        ]
        | None
    )
    best_time: str | None
    confidence: Annotated[Decimal, Field(ge=0, le=1)]
    authorized: bool


class OutreachRecord(Contract):
    outreach_id: SynId
    member_id: SynId
    phone: Phone | None
    channel: Literal["call", "sms", "mail"]
    attempted_at: AwareDatetime
    outcome: Literal["answered", "no_answer", "voicemail", "disconnected", "returned_undeliverable"]
    language_used: str | None
    cm_name: str | None


class PreferenceRecord(Contract):
    member_id: SynId
    preferred_language: str | None
    proxy_language: str | None
    assigned_cm: str | None
    cm_language_required: str | None


CONTRACTS = (
    StreamContract("cm_platform", "consents", "json", ConsentRecord, "stg_cm_consents"),
    StreamContract(
        "cm_platform", "contact_points", "json", ContactPointRecord, "stg_cm_contact_points"
    ),
    StreamContract("cm_platform", "outreach", "json", OutreachRecord, "stg_cm_outreach"),
    StreamContract("cm_platform", "preferences", "json", PreferenceRecord, "stg_cm_preferences"),
)
