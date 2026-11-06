from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import NonNegativeInt

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class LtssAideHoursRow(Contract):
    """State Medicaid LTSS file: authorised personal-care aide hours."""

    member_id: SynId
    service: str
    reassessment_date: date
    prior_hours_per_week: Decimal | None
    authorized_hours_per_week: Decimal
    effective_date: date | None
    notice_date: date | None
    appeal_window_days: NonNegativeInt | None
    as_of: date


class NemtTripRow(Contract):
    """Non-emergency medical transport broker trips."""

    trip_id: SynId
    member_id: SynId
    trip_date: date
    pickup_address: str | None
    destination: str | None
    status: Literal["completed", "no_show", "cancelled"]
    as_of: date


CONTRACTS = (
    StreamContract(
        "medicaid",
        "ltss_aide_hours",
        "csv",
        LtssAideHoursRow,
        "stg_ltss_aide_hours",
        as_of_field="as_of",
    ),
    StreamContract(
        "medicaid", "nemt_trips", "csv", NemtTripRow, "stg_nemt_trips", as_of_field="as_of"
    ),
)
