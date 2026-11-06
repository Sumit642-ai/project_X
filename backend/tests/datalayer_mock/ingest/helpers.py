import csv
from collections.abc import Sequence
from pathlib import Path

from app.synth.layouts import LAYOUT_BY_STREAM

PHARMACY_COLUMNS = LAYOUT_BY_STREAM["pharmacy_ncpdp"].columns


def pharmacy_rows(count: int) -> list[dict[str, str]]:
    return [
        {
            "rx_claim_id": f"SYN-RX-{i:06d}",
            "member_id": f"SYN-{6 + i % 45:03d}",
            "fill_date": "2026-10-01",
            "ndc": "99014-0001-30",
            "drug_name": "Lisinopril",
            "strength": "10 mg",
            "sig": "1 tablet daily",
            "quantity": "30",
            "days_supply": "30",
            "claim_status": "paid",
            "reject_code": "",
            "reject_reason": "",
            "prescriber": "Dr R. Okafor",
            "pharmacy_name": "Northside Drug",
            "pharmacy_phone_on_profile": f"555-01{i % 100:02d}",
            "profile_phone_as_of": "2026-10-01",
            "patient_pay": "0.00",
        }
        for i in range(count)
    ]


def write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), lineterminator="\n", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_pharmacy(
    raw: Path,
    load_date: str,
    rows: Sequence[dict[str, str]],
    columns: Sequence[str] = PHARMACY_COLUMNS,
) -> Path:
    return write_csv(raw / "pharmacy" / f"pharmacy_ncpdp_{load_date}.csv", columns, rows)
