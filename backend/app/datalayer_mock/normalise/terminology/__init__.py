"""Small local terminology tables (CSV) for the codes that appear in the synthetic feeds."""

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Icd10Entry:
    code: str
    display: str
    condition_group: str


@dataclass(frozen=True)
class NdcEntry:
    ndc: str
    ingredient: str
    strength: str
    drug_class: str
    product_name: str


@dataclass(frozen=True)
class LoincEntry:
    loinc: str
    concept: str
    display: str
    unit: str


def _rows(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache
def icd10() -> dict[str, Icd10Entry]:
    return {r["code"]: Icd10Entry(**r) for r in _rows("icd10.csv")}


@lru_cache
def ndc() -> dict[str, NdcEntry]:
    return {r["ndc"]: NdcEntry(**r) for r in _rows("ndc.csv")}


@lru_cache
def loinc() -> dict[str, LoincEntry]:
    return {r["loinc"]: LoincEntry(**r) for r in _rows("loinc.csv")}


def _name_key(text: str) -> str:
    return " ".join(text.lower().replace("/", " / ").split())


@lru_cache
def drug_names() -> dict[str, NdcEntry]:
    """Product or ingredient name -> an entry (any strength), for documents without NDCs."""
    names: dict[str, NdcEntry] = {}
    for entry in ndc().values():
        names.setdefault(_name_key(entry.product_name), entry)
        names.setdefault(_name_key(entry.ingredient), entry)
    return names


def name_key(text: str) -> str:
    return _name_key(text)
