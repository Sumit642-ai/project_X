"""Fixed reference values shared by the hero and background generators."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.clock import PLAN_TZ, REFERENCE_INSTANT

SEED = 20261109
TZ = PLAN_TZ
REF = REFERENCE_INSTANT
REF_DATE = REF.date()
CLAIMS_LOADED_THROUGH = date(2026, 9, 25)
PHARMACY_HISTORY_START = date(2026, 5, 1)
PLAN = "Evergreen"
STATE = "OH"

# Load date carried in each file name.
LOAD_DATES = {
    "eligibility": date(2026, 11, 8),
    "claims": date(2026, 11, 8),
    "pharmacy": date(2026, 11, 8),
    "um": date(2026, 11, 8),
    "formulary": date(2026, 11, 1),
    "care_gaps": date(2026, 11, 8),
    "labs": date(2026, 11, 8),
    "documents": date(2026, 11, 8),
    "cm_platform": date(2026, 11, 9),
    "ltss": date(2026, 10, 8),  # I-16: state file lag, 32 days before the reference clock
    "nemt": date(2026, 11, 1),
    "sdoh": date(2026, 11, 8),
    "part2": date(2026, 11, 1),
    "risk": date(2026, 11, 1),
}

LOB_PLAN_TYPES = ("MA-PPO", "MEDICAID", "DUAL", "DSNP")


@dataclass(frozen=True)
class Drug:
    key: str
    name: str
    strengths: tuple[str, ...]
    sig: str
    days_supply: int
    tier: int | None  # None = non-formulary
    pa_required: bool = False
    step_therapy: bool = False
    alternative: str | None = None


# Order matters: NDC codes are assigned by position. NDCs are synthetic (labeler prefix 99).
DRUGS: tuple[Drug, ...] = (
    Drug("furosemide", "Furosemide", ("20 mg", "40 mg", "80 mg"), "1 tablet daily", 30, 1),
    Drug(
        "sacubitril_valsartan",
        "Sacubitril/valsartan",
        ("24/26 mg",),
        "1 tablet twice daily",
        30,
        3,
        pa_required=True,
    ),
    Drug(
        "metoprolol_succinate", "Metoprolol succinate", ("25 mg", "50 mg"), "1 tablet daily", 30, 1
    ),
    Drug("metformin", "Metformin", ("500 mg", "1000 mg"), "1 tablet twice daily", 90, 1),
    Drug("glipizide", "Glipizide", ("5 mg",), "1 tablet daily", 90, 1),
    Drug(
        "semaglutide",
        "Semaglutide",
        ("0.25 mg",),
        "0.25 mg weekly",
        28,
        None,
        alternative="Dulaglutide",
    ),
    Drug("dulaglutide", "Dulaglutide", ("0.75 mg",), "0.75 mg weekly", 28, 3, step_therapy=True),
    Drug(
        "budesonide_formoterol",
        "Budesonide/formoterol inhaler",
        ("160/4.5 mcg",),
        "2 puffs twice daily",
        30,
        3,
    ),
    Drug(
        "albuterol", "Albuterol rescue inhaler", ("90 mcg",), "2 puffs every 4-6 h as needed", 25, 2
    ),
    Drug("buprenorphine_naloxone", "Buprenorphine/naloxone", ("8/2 mg",), "1 film daily", 14, 2),
    Drug("lamotrigine", "Lamotrigine", ("100 mg",), "1 tablet daily", 14, 1),
    Drug("donepezil", "Donepezil", ("10 mg",), "1 tablet at bedtime", 30, 1),
    Drug("amlodipine", "Amlodipine", ("5 mg", "10 mg"), "1 tablet daily", 30, 1),
    Drug("lisinopril", "Lisinopril", ("10 mg", "20 mg"), "1 tablet daily", 30, 1),
    Drug("atorvastatin", "Atorvastatin", ("20 mg", "40 mg"), "1 tablet daily", 90, 1),
    Drug("carvedilol", "Carvedilol", ("12.5 mg", "25 mg"), "1 tablet twice daily", 30, 1),
    Drug("sertraline", "Sertraline", ("50 mg", "100 mg"), "1 tablet daily", 30, 1),
    Drug("levothyroxine", "Levothyroxine", ("50 mcg", "75 mcg"), "1 tablet daily", 90, 1),
    Drug("apixaban", "Apixaban", ("5 mg",), "1 tablet twice daily", 30, 3),
    Drug("tiotropium", "Tiotropium inhaler", ("18 mcg",), "1 capsule inhaled daily", 30, 3),
    Drug(
        "fluticasone_salmeterol",
        "Fluticasone/salmeterol inhaler",
        ("250/50 mcg",),
        "1 puff twice daily",
        30,
        2,
    ),
    Drug("gabapentin", "Gabapentin", ("300 mg",), "1 capsule three times daily", 30, 1),
    Drug("insulin_glargine", "Insulin glargine", ("100 units/mL",), "20 units at bedtime", 30, 2),
    Drug("empagliflozin", "Empagliflozin", ("10 mg",), "1 tablet daily", 30, 3),
    Drug("omeprazole", "Omeprazole", ("20 mg",), "1 capsule daily", 30, 1),
    # Non-formulary drugs used for background I-06 rejects.
    Drug(
        "dapagliflozin",
        "Dapagliflozin",
        ("10 mg",),
        "1 tablet daily",
        30,
        None,
        alternative="Empagliflozin",
    ),
    Drug(
        "olmesartan", "Olmesartan", ("20 mg",), "1 tablet daily", 30, None, alternative="Lisinopril"
    ),
    Drug(
        "esomeprazole",
        "Esomeprazole",
        ("40 mg",),
        "1 capsule daily",
        30,
        None,
        alternative="Omeprazole",
    ),
    Drug(
        "insulin_degludec",
        "Insulin degludec",
        ("100 units/mL",),
        "20 units daily",
        30,
        None,
        alternative="Insulin glargine",
    ),
)
DRUG_BY_KEY = {d.key: d for d in DRUGS}
NON_FORMULARY_BACKGROUND = ("dapagliflozin", "olmesartan", "esomeprazole", "insulin_degludec")

TIER_COPAY = {1: Decimal("0.00"), 2: Decimal("10.00"), 3: Decimal("47.00")}


def ndc(drug_key: str, strength: str) -> str:
    drug_index = next(i for i, d in enumerate(DRUGS) if d.key == drug_key)
    strength_index = DRUG_BY_KEY[drug_key].strengths.index(strength)
    return f"99{drug_index + 1:03d}-{strength_index + 1:04d}-30"


@dataclass(frozen=True)
class Condition:
    key: str
    icd10: str
    drugs: tuple[str, ...]
    lab: str | None = None


CONDITIONS: tuple[Condition, ...] = (
    Condition("htn", "I10", ("lisinopril", "amlodipine")),
    Condition("t2dm", "E11.9", ("metformin", "insulin_glargine", "empagliflozin"), "hba1c"),
    Condition("hld", "E78.5", ("atorvastatin",)),
    Condition("hf", "I50.22", ("furosemide", "carvedilol"), "ntprobnp"),
    Condition("copd", "J44.9", ("tiotropium",)),
    Condition("asthma", "J45.40", ("fluticasone_salmeterol", "albuterol")),
    Condition("ckd3", "N18.30", (), "egfr"),
    Condition("depression", "F32.9", ("sertraline",)),
    Condition("hypothyroid", "E03.9", ("levothyroxine",)),
    Condition("afib", "I48.91", ("apixaban",)),
    Condition("neuropathy", "G62.9", ("gabapentin",)),
    Condition("gerd", "K21.9", ("omeprazole",)),
)
CONDITION_BY_KEY = {c.key: c for c in CONDITIONS}
OLDER_ADULT_CONDITIONS = ("htn", "t2dm", "hld", "hf", "copd", "ckd3", "afib", "hypothyroid", "gerd")
YOUNGER_ADULT_CONDITIONS = ("asthma", "depression", "t2dm", "htn", "neuropathy", "gerd", "hld")

LABS = {
    "hba1c": ("4548-4", "Hemoglobin A1c", "%"),
    "ntprobnp": ("33762-6", "NT-proBNP", "pg/mL"),
    "egfr": ("33914-3", "eGFR", "mL/min/1.73m2"),
}

FACILITIES = {
    "STBRIGID": "St Brigid Regional",
    "LAKEVIEW": "Lakeview ED",
    "MERCYBH": "Mercy BH Pavilion",
    "NORTHFLD": "Northfield General",
    "CARDINAL": "Cardinal Valley Hospital",
}
