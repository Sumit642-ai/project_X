"""One schema contract per feed. The registry below is keyed by stream name."""

from app.datalayer_mock.ingest.contracts import (
    adt,
    care_gaps,
    claims,
    cm_platform,
    documents,
    eligibility,
    formulary,
    labs,
    medicaid,
    part2,
    pharmacy,
    risk,
    sdoh,
    um,
)
from app.datalayer_mock.ingest.contracts.base import Contract, StreamContract

# Load order: reference data and members first, then member-level feeds, then events.
FEED_ORDER: tuple[str, ...] = (
    "formulary",
    "eligibility",
    "risk",
    "cm_platform",
    "claims",
    "pharmacy",
    "um",
    "care_gaps",
    "labs",
    "medicaid",
    "sdoh",
    "documents",
    "adt",
    "part2",
)

CONTRACTS: dict[str, StreamContract] = {
    c.stream: c
    for module in (
        formulary,
        eligibility,
        cm_platform,
        claims,
        pharmacy,
        um,
        care_gaps,
        labs,
        medicaid,
        sdoh,
        documents,
        adt,
        part2,
        risk,
    )
    for c in module.CONTRACTS
}

__all__ = ["CONTRACTS", "FEED_ORDER", "Contract", "StreamContract"]
