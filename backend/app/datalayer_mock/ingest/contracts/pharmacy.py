from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import PositiveInt, model_validator

from app.datalayer_mock.ingest.contracts.base import Contract, Ndc, Phone, StreamContract, SynId


class PharmacyClaimRow(Contract):
    """NCPDP-style pharmacy claim, including rejected claims."""

    rx_claim_id: SynId
    member_id: SynId
    fill_date: date
    ndc: Ndc
    drug_name: str
    strength: str
    sig: str | None
    quantity: Decimal
    days_supply: PositiveInt
    claim_status: Literal["paid", "rejected", "reversed"]
    reject_code: str | None
    reject_reason: str | None
    prescriber: str | None
    pharmacy_name: str | None
    pharmacy_phone_on_profile: Phone | None
    profile_phone_as_of: date | None
    patient_pay: Decimal | None

    @model_validator(mode="after")
    def _rejects_carry_a_reason(self) -> Self:
        if self.claim_status == "rejected" and not (self.reject_code and self.reject_reason):
            raise ValueError("rejected claims need reject_code and reject_reason")
        if self.claim_status != "rejected" and (self.reject_code or self.reject_reason):
            raise ValueError("only rejected claims carry a reject code or reason")
        return self


CONTRACTS = (StreamContract("pharmacy", "pharmacy_ncpdp", "csv", PharmacyClaimRow, "stg_pharmacy"),)
