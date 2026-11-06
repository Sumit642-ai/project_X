import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import hl7

from app.synth.catalog import REF_DATE

BACKEND_DIR = Path(__file__).resolve().parents[2]
PHONE = re.compile(r"^555-01\d\d$")
PHONE_LIKE = re.compile(r"(?<!\d)\d{3}-\d{4}(?!\d)")
NUMBER_COLUMNS = ("phone", "pharmacy_phone_on_profile")


def read_csv(raw: Path, pattern: str) -> list[dict[str, str]]:
    (path,) = raw.glob(pattern)
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(raw: Path, pattern: str) -> list[dict[str, Any]]:
    (path,) = raw.glob(pattern)
    data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def checksums(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_two_runs_of_make_synth_produce_identical_checksums(tmp_path: Path) -> None:
    # Separate processes with different hash seeds: catches any set/dict-order dependence.
    for name, hash_seed in (("a", "1"), ("b", "2")):
        subprocess.run(
            [sys.executable, "-m", "app.synth", "--out", str(tmp_path / name)],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
        )

    first, second = checksums(tmp_path / "a"), checksums(tmp_path / "b")
    assert len(first) > 100
    assert first == second


def test_raymond_furosemide_and_sacubitril_valsartan(generated_raw: Path) -> None:
    rows = [r for r in read_csv(generated_raw, "pharmacy/*.csv") if r["member_id"] == "SYN-001"]
    furosemide = [r for r in rows if r["drug_name"] == "Furosemide"]

    assert [
        (r["strength"], r["fill_date"], r["days_supply"], r["claim_status"]) for r in furosemide
    ] == [("40 mg", "2026-09-30", "30", "paid")]
    assert not any(r["strength"] == "80 mg" for r in furosemide)
    (arni,) = [r for r in rows if r["drug_name"] == "Sacubitril/valsartan"]
    assert (arni["claim_status"], arni["reject_reason"]) == ("rejected", "PA required")


def test_every_adt_message_is_valid_hl7_v2_with_a_blank_diagnosis(generated_raw: Path) -> None:
    files = sorted((generated_raw / "adt").glob("*.hl7"))
    assert len(files) >= 6
    control_ids = []
    for path in files:
        raw = path.read_bytes().decode("utf-8")
        assert "\n" not in raw, path.name  # HL7 v2 segments are separated by CR only
        message = hl7.parse(raw)
        assert [str(s[0]) for s in message] == ["MSH", "EVN", "PID", "PV1", "DG1"], path.name
        assert message["MSH.F12"] == "2.5.1"
        assert message["MSH.F9.R1.C1"] == "ADT"
        trigger = message["MSH.F9.R1.C2"]
        assert trigger in ("A01", "A03", "A04")
        assert (
            message["MSH.F9.R1.C3"]
            == {"A01": "ADT_A01", "A03": "ADT_A03", "A04": "ADT_A01"}[trigger]
        )
        assert message["EVN.F1"] == trigger
        assert message["PID.F3.R1.C1"].startswith("SYN-")
        assert message["DG1.F3"] == "" and message["DG1.F4"] == "", path.name
        control_ids.append(message["MSH.F10"])
    assert len(set(control_ids)) == len(control_ids)


def test_every_phone_number_is_555_01xx(generated_raw: Path) -> None:
    seen = 0
    for path in generated_raw.rglob("*"):
        if path.is_file():
            for match in PHONE_LIKE.findall(path.read_text(encoding="utf-8")):
                assert PHONE.match(match), f"{path.name}: {match}"
                seen += 1
    assert seen > 100

    phone_fields = []
    for path in generated_raw.rglob("*.csv"):
        for row in csv.DictReader(path.open(encoding="utf-8", newline="")):
            phone_fields += [v for k, v in row.items() if k in NUMBER_COLUMNS and v]
    for path in generated_raw.rglob("*.json"):
        if path.name != "MANIFEST.json":
            phone_fields += [r["phone"] for r in json.loads(path.read_text()) if r.get("phone")]
    for path in (generated_raw / "adt").glob("*.hl7"):
        message = hl7.parse(path.read_bytes().decode("utf-8"))  # keep CR separators
        phone_fields += [v for v in [message["PID.F13.R1.C1"]] if v]
    assert len(phone_fields) > 100
    assert all(PHONE.match(v) for v in phone_fields)


def test_every_member_id_is_synthetic(generated_raw: Path) -> None:
    for path in generated_raw.rglob("*.csv"):
        for row in csv.DictReader(path.open(encoding="utf-8", newline="")):
            for key in ("member_id", "rx_claim_id", "claim_id"):
                if key in row:
                    assert row[key].startswith("SYN-"), (path.name, row[key])


def test_manifest_lists_every_file_with_counts_checksums_and_imperfections(
    generated_raw: Path,
) -> None:
    manifest = json.loads((generated_raw / "MANIFEST.json").read_text(encoding="utf-8"))
    on_disk = checksums(generated_raw)
    on_disk.pop("MANIFEST.json")

    assert {f["path"]: f["sha256"] for f in manifest["files"]} == on_disk
    for entry in manifest["files"]:
        path = generated_raw / entry["path"]
        if path.suffix == ".csv":
            count = len(list(csv.DictReader(path.open(encoding="utf-8", newline=""))))
        elif path.suffix == ".json":
            count = len(json.loads(path.read_text(encoding="utf-8")))
        else:
            count = 1
        assert entry["rows"] == count, entry["path"]

    imperfections = {i["id"]: i for i in manifest["imperfections"]}
    assert list(imperfections) == [f"I-{n:02d}" for n in range(1, 18)]
    for imperfection in imperfections.values():
        assert imperfection["hero_members"], imperfection["id"]
        expected = 0 if imperfection["id"] in ("I-12", "I-16") else 5
        assert len(imperfection["background_members"]) == expected, imperfection["id"]
    assert manifest["claims_loaded_through"] == "2026-09-25"
    assert manifest["reference_clock"] == "2026-11-09T08:00:00-05:00"


def test_hero_ages_and_plans_match_the_annex(generated_raw: Path) -> None:
    rows = {r["member_id"]: r for r in read_csv(generated_raw, "eligibility/*.csv")}

    def age(dob: str) -> int:
        born = date.fromisoformat(dob)
        return REF_DATE.year - born.year - ((REF_DATE.month, REF_DATE.day) < (born.month, born.day))

    assert {
        m: (age(rows[m]["dob"]), rows[m]["lob"], rows[m]["language"])
        for m in ("SYN-001", "SYN-002", "SYN-003", "SYN-004", "SYN-005")
    } == {
        "SYN-001": (76, "MA-PPO", "en"),
        "SYN-002": (68, "MA-PPO", "vi"),
        "SYN-003": (54, "DUAL", "en"),
        "SYN-004": (34, "MEDICAID", "en"),
        "SYN-005": (84, "DSNP", "ht"),
    }
    assert rows["SYN-003"]["pcp"] == ""  # none attributed
    assert len([m for m in rows if not m.endswith("-M")]) == 50


def test_planted_hero_imperfections_are_in_the_files(generated_raw: Path) -> None:
    eligibility = {r["member_id"]: r for r in read_csv(generated_raw, "eligibility/*.csv")}
    maiden = eligibility["SYN-004-M"]
    assert (maiden["last_name"], maiden["first_name"], maiden["dob"]) == (
        "Delaney",
        "Kayla",
        eligibility["SYN-004"]["dob"],
    )  # I-14
    assert "SYN-001-H" not in eligibility  # I-01 exists only in hospital data
    assert eligibility["SYN-005"]["rep_form_expires"] == "2026-09-30"  # I-15

    raymond_adt = [
        p for p in (generated_raw / "adt").glob("*.hl7") if "SYN-001-H^" in p.read_text()
    ]
    assert len(raymond_adt) == 2  # I-01 / I-05: admit and discharge from St Brigid

    requests = read_csv(generated_raw, "documents/hie_requests_*.csv")
    assert [
        (r["member_id"], r["status"], r["requested_at"])
        for r in requests
        if r["member_id"] == "SYN-001"
    ] == [("SYN-001", "not_received", "2026-11-07T15:02:00-05:00")]  # I-04
    summaries = [
        p
        for p in (generated_raw / "documents").glob("*.xml")
        if "SYN-001" in p.read_text() and "18842-5" in p.read_text()
    ]
    assert summaries == []

    claims = read_csv(generated_raw, "claims/*.csv")
    assert {r["claims_loaded_through"] for r in claims} == {"2026-09-25"}
    assert not [
        r for r in claims if r["member_id"] == "SYN-001" and r["claim_type"] == "inpatient"
    ]  # I-05

    (ltss,) = [
        r
        for r in read_csv(generated_raw, "medicaid/ltss_aide_hours_*.csv")
        if r["member_id"] == "SYN-005"
    ]
    assert REF_DATE - date.fromisoformat(ltss["as_of"]) == timedelta(days=32)  # I-16
    assert (ltss["prior_hours_per_week"], ltss["authorized_hours_per_week"]) == ("20", "12")

    part2 = read_csv(generated_raw, "part2/*.csv")
    assert {r["member_id"] for r in part2} == {"SYN-004"}  # I-12

    consents = read_json(generated_raw, "cm_platform/consents_*.json")
    sms_numbers = {c["phone"] for c in consents if c["consent_type"] == "tcpa_sms"}
    assert "555-0188" not in sms_numbers  # I-11
    (auth,) = [r for r in read_csv(generated_raw, "um/*.csv") if r["member_id"] == "SYN-005"]
    assert (auth["status"], auth["decision_due"]) == ("pending", "2026-11-05")  # I-17
