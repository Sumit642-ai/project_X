"""Transparent weighted scorer for records that arrive without a plan member ID.

confidence = sum(weight x level score) over the fields below. Every field's level, score and
contribution is returned so a reviewer can see exactly why a pair scored what it did.
A field missing on either side contributes 0 (it is never assumed to agree).
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.datalayer_mock.identity.jaro_winkler import jaro_winkler

WEIGHTS: dict[str, float] = {
    "first_name": 0.22,
    "last_name": 0.18,
    "dob": 0.32,
    "sex": 0.04,
    "address": 0.10,
    "phone": 0.14,
}
SIMILAR_NAME = 0.92  # Jaro-Winkler at or above this counts as a near match (typo, short form)

AUTO_LINK_THRESHOLD = Decimal("0.90")
REVIEW_THRESHOLD = Decimal("0.70")

_STREET_WORDS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "DRIVE": "DR",
    "APARTMENT": "APT",
    "BOULEVARD": "BLVD",
}


@dataclass(frozen=True)
class Demographics:
    first_name: str | None
    last_name: str | None
    dob: date | None
    sex: str | None
    address_line1: str | None
    city: str | None
    zip: str | None
    phone: str | None


@dataclass(frozen=True)
class FieldScore:
    weight: float
    level: str
    score: float
    contribution: float
    source: str | None
    candidate: str | None


@dataclass(frozen=True)
class MatchScore:
    confidence: Decimal
    fields: dict[str, FieldScore]

    def as_json(self) -> dict[str, dict[str, object]]:
        return {name: vars(f) for name, f in self.fields.items()}


def normalise_name(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(re.sub(r"[^A-Z ]", " ", value.upper()).split()) or None


def normalise_address(value: str | None) -> str | None:
    if not value:
        return None
    words = re.sub(r"[^A-Z0-9 ]", " ", value.upper()).split()
    return " ".join(_STREET_WORDS.get(w, w) for w in words) or None


def _digits(value: str | None) -> str | None:
    return re.sub(r"\D", "", value) or None if value else None


def _name_level(a: str | None, b: str | None) -> tuple[str, float]:
    if not a or not b:
        return "missing", 0.0
    if a == b:
        return "exact", 1.0
    if jaro_winkler(a, b) >= SIMILAR_NAME:
        return "similar", 0.9
    return "different", 0.0


def score(source: Demographics, candidate: Demographics) -> MatchScore:
    fields: dict[str, tuple[str, float, str | None, str | None]] = {}

    first_a, first_b = normalise_name(source.first_name), normalise_name(candidate.first_name)
    fields["first_name"] = (*_name_level(first_a, first_b), first_a, first_b)

    dob_a = source.dob.isoformat() if source.dob else None
    dob_b = candidate.dob.isoformat() if candidate.dob else None
    dob_level = (
        ("missing", 0.0)
        if not dob_a or not dob_b
        else (("exact", 1.0) if dob_a == dob_b else ("different", 0.0))
    )
    fields["dob"] = (*dob_level, dob_a, dob_b)

    last_a, last_b = normalise_name(source.last_name), normalise_name(candidate.last_name)
    last_level = _name_level(last_a, last_b)
    if (
        last_level[0] == "different"
        and fields["first_name"][0] == "exact"
        and dob_level[0] == "exact"
    ):
        # Same first name and date of birth, different surname: e.g. maiden or married name.
        last_level = ("possible surname change", 0.9)
    fields["last_name"] = (*last_level, last_a, last_b)

    sex_a, sex_b = source.sex or None, candidate.sex or None
    sex_level = (
        ("missing", 0.0)
        if not sex_a or not sex_b
        else (("exact", 1.0) if sex_a == sex_b else ("different", 0.0))
    )
    fields["sex"] = (*sex_level, sex_a, sex_b)

    line_a, line_b = (
        normalise_address(source.address_line1),
        normalise_address(candidate.address_line1),
    )
    if not line_a or not line_b:
        address_level = ("missing", 0.0)
    elif line_a == line_b and source.zip == candidate.zip:
        address_level = ("exact", 1.0)
    elif source.zip and source.zip == candidate.zip:
        address_level = ("same zip", 0.6)
    elif source.city and normalise_name(source.city) == normalise_name(candidate.city):
        address_level = ("same city", 0.4)
    else:
        address_level = ("different", 0.0)
    fields["address"] = (
        *address_level,
        f"{line_a} {source.zip or ''}".strip() if line_a else None,
        f"{line_b} {candidate.zip or ''}".strip() if line_b else None,
    )

    phone_a, phone_b = _digits(source.phone), _digits(candidate.phone)
    phone_level = (
        ("missing", 0.0)
        if not phone_a or not phone_b
        else (("exact", 1.0) if phone_a == phone_b else ("different", 0.0))
    )
    fields["phone"] = (*phone_level, source.phone, candidate.phone)

    scored = {
        name: FieldScore(WEIGHTS[name], level, value, round(WEIGHTS[name] * value, 4), a, b)
        for name, (level, value, a, b) in fields.items()
    }
    total = sum((Decimal(str(f.contribution)) for f in scored.values()), Decimal("0"))
    return MatchScore(total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), scored)


def classify(confidence: Decimal) -> str | None:
    """auto_linked >= 0.90; needs_review 0.70-0.89; below 0.70 no link is created."""
    if confidence >= AUTO_LINK_THRESHOLD:
        return "auto_linked"
    if confidence >= REVIEW_THRESHOLD:
        return "needs_review"
    return None
