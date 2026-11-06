"""Consent enforcement, in one place.

Every decision about calling, texting, third-party contact, transcription, Part 2 reveal and
masking goes through this module. tests/consent/test_single_place.py fails the build if code
elsewhere in app/ checks consent directly.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.encounters.models import Encounter
from app.facts.models import ConsentRecord, ContactPoint, Fact

# Records are Part 2 only when their source program is on this allowlist. Records from any
# other program in the program-records feed are "unverified": masked until classified.
PART2_PROGRAM_ALLOWLIST = frozenset({"New Dawn Recovery"})
VISIBLE = "none"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    consent_id: int | None = None

    def __bool__(self) -> bool:
        return self.allowed


# --- consents ---------------------------------------------------------------------------------


def consent_is_valid(consent: ConsentRecord, on: date) -> bool:
    return consent.is_valid(on)


def sms_consented_numbers(consents: Iterable[ConsentRecord], on: date) -> set[tuple[str, str]]:
    """(member_id, phone) pairs with a valid TCPA SMS consent for that exact number."""
    return {
        (c.member_id, c.phone)
        for c in consents
        if c.type == "tcpa_sms" and c.phone and c.is_valid(on)
    }


def is_representative(consent: ConsentRecord) -> bool:
    return consent.type == "personal_representative"


# --- contacts ---------------------------------------------------------------------------------


def contact_status(contact: ContactPoint) -> tuple[bool, str | None]:
    """(callable, reason it is not) for display and ranking."""
    if not contact.authorised:
        return False, "not authorised"
    if not contact.callable:
        return False, "disconnected"
    return True, None


def is_authorised(contact: ContactPoint) -> bool:
    return contact.authorised


def has_sms_consent(contact: ContactPoint) -> bool:
    return contact.consent_sms


def callable_contacts(contacts: Iterable[ContactPoint]) -> list[ContactPoint]:
    return [c for c in contacts if contact_status(c)[0]]


def authorised_contacts(contacts: Iterable[ContactPoint]) -> list[ContactPoint]:
    return [c for c in contacts if c.authorised]


def _contact(session: Session, member_id: str, number: str) -> ContactPoint | None:
    return session.scalars(
        select(ContactPoint).where(
            ContactPoint.member_id == member_id, ContactPoint.number == number
        )
    ).first()


def can_contact_third_party(session: Session, member_id: str, contact: ContactPoint) -> Decision:
    if contact.owner == "self":
        return Decision(True, "member's own number")
    if not contact.authorised:
        return Decision(
            False,
            f"{contact.number} belongs to a {contact.owner.replace('_', ' ')} "
            "without authorisation for this member",
        )
    return Decision(True, f"{contact.owner.replace('_', ' ')} authorised")


def can_transcribe(encounter: Encounter) -> Decision:
    """Transcription (and the AI draft built from it) needs the member's agreement on this call."""
    if not encounter.identity_verified:
        return Decision(False, "verify the member's identity first")
    if not encounter.transcription_consent:
        return Decision(False, "the member has not agreed to transcription on this call")
    return Decision(True, "member agreed to transcription on this call")


def can_call(session: Session, member_id: str, number: str, *, clock: Clock) -> Decision:
    contact = _contact(session, member_id, number)
    if contact is None:
        return Decision(False, f"{number} is not on {member_id}'s contact ladder")
    if not contact.authorised:
        return Decision(False, f"{number} is not authorised for this member")
    return can_contact_third_party(session, member_id, contact)


def can_sms(session: Session, member_id: str, number: str, *, clock: Clock) -> Decision:
    """Hard rule: SMS only with valid TCPA consent for that exact number. No override."""
    allowed_to_call = can_call(session, member_id, number, clock=clock)
    if not allowed_to_call:
        return allowed_to_call
    today = clock.now().astimezone(PLAN_TZ).date()
    consents = session.scalars(
        select(ConsentRecord).where(
            ConsentRecord.member_id == member_id,
            ConsentRecord.type == "tcpa_sms",
            ConsentRecord.phone == number,
        )
    )
    valid = next((c for c in consents if c.is_valid(today)), None)
    if valid is None:
        return Decision(False, f"SMS to {number} blocked: no TCPA consent for this number")
    return Decision(True, "TCPA consent on file", valid.id)


# --- Part 2 -----------------------------------------------------------------------------------


def program_sensitivity(program: str | None) -> str:
    """Sensitivity for a record from a substance-use program feed."""
    return "part2" if program in PART2_PROGRAM_ALLOWLIST else "unverified"


def is_masked(fact: Fact) -> bool:
    return fact.sensitivity != VISIBLE


def revealable_facts(session: Session, member_id: str) -> list[Fact]:
    """Part 2 records from allowlisted programs. Unverified programs are never revealable."""
    return list(
        session.scalars(
            select(Fact)
            .where(
                Fact.member_id == member_id,
                Fact.sensitivity == "part2",
                Fact.superseded_by.is_(None),
            )
            .order_by(Fact.event_date, Fact.id)
        )
    )


def can_reveal_part2(session: Session, member_id: str, user: Any, *, clock: Clock) -> Decision:
    if getattr(user, "role", None) != "cm":
        return Decision(False, "only the assigned case manager may reveal Part 2 records")
    notes = revealable_facts(session, member_id)
    if not notes:
        return Decision(False, "no Part 2 records")
    today = clock.now().astimezone(PLAN_TZ).date()
    programs = {n.value.get("program_name") for n in notes}
    consents = [
        c
        for c in session.scalars(
            select(ConsentRecord).where(
                ConsentRecord.member_id == member_id, ConsentRecord.type == "part2"
            )
        )
        if c.program in programs
    ]
    valid = next((c for c in consents if c.is_valid(today)), None)
    if valid is None:
        why = (
            f"Part 2 consent is not valid on {today.isoformat()}"
            if consents
            else "no Part 2 consent on file"
        )
        return Decision(False, why)
    return Decision(True, "valid Part 2 consent", valid.id)
