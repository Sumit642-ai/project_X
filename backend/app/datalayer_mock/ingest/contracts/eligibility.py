from datetime import date
from typing import Annotated, Literal

from pydantic import StringConstraints

from app.datalayer_mock.ingest.contracts.base import Contract, Phone, StreamContract, SynId


class EligibilityRow(Contract):
    """834-style eligibility extract, one row per member record."""

    member_id: SynId
    last_name: str
    first_name: str
    dob: date
    sex: Literal["F", "M", "U"]
    plan: str
    lob: Literal["MA-PPO", "MEDICAID", "DUAL", "DSNP"]
    state: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    language: str | None
    pcp: str | None
    phone: Phone | None
    phone_type: Literal["mobile", "landline"] | None
    phone_as_of: date | None
    address_line1: str | None
    city: str | None
    zip: Annotated[str, StringConstraints(pattern=r"^\d{5}$")] | None
    address_as_of: date | None
    effective_date: date
    term_date: date | None
    rep_name: str | None
    rep_relationship: str | None
    rep_form_expires: date | None
    medicaid_redetermination_due: date | None


CONTRACTS = (
    StreamContract("eligibility", "eligibility_834", "csv", EligibilityRow, "stg_eligibility"),
)
