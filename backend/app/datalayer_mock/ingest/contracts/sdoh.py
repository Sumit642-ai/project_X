from datetime import date
from typing import Literal

from pydantic import NonNegativeInt

from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract, SynId


class ScreenRow(Contract):
    """HRA and SDOH screens."""

    screen_id: SynId
    member_id: SynId
    instrument: Literal["HRA", "AHC-HRSN", "ZBI-4"]
    domain: Literal["general", "housing", "caregiver_strain"]
    screen_date: date
    result: str | None
    score: NonNegativeInt | None
    score_max: NonNegativeInt | None
    risk_level: Literal["low", "moderate", "high"] | None


CONTRACTS = (StreamContract("sdoh", "screens", "csv", ScreenRow, "stg_sdoh_screens"),)
