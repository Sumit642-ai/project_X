"""Feed deliveries in demo mode, through the real data-layer path.

A delivery writes a new snapshot file for a feed (the synthetic snapshot plus the demo's extra
rows) into data/demo/inbox/, ingests it with the frozen clock, and refreshes everything
downstream: normalisation, Facts, signals and scores, and tasks whose signals stopped firing.
A delivery to a paused feed is held and arrives when the feed resumes.
"""

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.clock import PLAN_TZ, Clock
from app.core.config import REPO_ROOT, Settings
from app.datalayer_mock.identity import run_matching
from app.datalayer_mock.ingest import ingest_file
from app.datalayer_mock.ingest.models import Load
from app.datalayer_mock.normalise.run import run_normalisation
from app.demo.state import DemoState
from app.encounters.service import resolve_tasks_by_data
from app.facts import refresh_facts
from app.scoring.service import score_members

INTRADAY_SCRIPT = REPO_ROOT / "data" / "seed" / "demo" / "intraday.json"
# feed -> (raw sub-directory, file stem)
SNAPSHOTS = {
    "pharmacy": ("pharmacy", "pharmacy_ncpdp"),
    "um": ("um", "auth_requests"),
    "consents": ("cm_platform", "consents"),
}
KAYLA, KAYLA_PROGRAM = "SYN-004", "New Dawn Recovery"
UNKNOWN_NDC_ROW = {
    "rx_claim_id": "SYN-RX-DEMO-NDC-01",
    "member_id": "SYN-003",
    "fill_date": "2026-11-09",
    "ndc": "99999-0042-30",
    "drug_name": "Zorvantide",
    "strength": "5 mg",
    "sig": "1 tablet daily",
    "quantity": "30",
    "days_supply": "30",
    "claim_status": "paid",
    "reject_code": "",
    "reject_reason": "",
    "prescriber": "Dr S. Brennan",
    "pharmacy_name": "Eastside Pharmacy",
    "pharmacy_phone_on_profile": "555-0188",
    "profile_phone_as_of": "2026-11-09",
    "patient_pay": "4.00",
}


@dataclass(frozen=True)
class Step:
    id: str
    at: str
    label: str
    story: str
    deliveries: list[dict[str, Any]]


def intraday_steps(path: Path = INTRADAY_SCRIPT) -> list[Step]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Step(**{k: v for k, v in s.items() if not k.startswith("_")}) for s in data["steps"]]


def _base_file(settings: Settings, feed: str) -> Path:
    folder, stem = SNAPSHOTS[feed]
    files = sorted((settings.raw_dir / folder).glob(f"{stem}_*.*"))
    if not files:
        raise FileNotFoundError(f"no synthetic {feed} snapshot in {settings.raw_dir / folder}")
    return files[-1]


def _csv_with_rows(base: Path, rows: list[dict[str, Any]]) -> str:
    text = base.read_text(encoding="utf-8")
    header = next(csv.reader(io.StringIO(text)))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, lineterminator="\n")
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in header})
    return text.rstrip("\n") + "\n" + out.getvalue()


def _consents(base: Path, events: list[str], today: date) -> str:
    """The CM platform's consent snapshot after the demo's expire/restore events for Kayla."""
    records: list[dict[str, Any]] = json.loads(base.read_text(encoding="utf-8"))
    current = next(
        r
        for r in records
        if r["member_id"] == KAYLA
        and r["consent_type"] == "part2"
        and r.get("program") == KAYLA_PROGRAM
    )
    for number, event in enumerate(events, start=1):
        if event == "expire":
            current["expires_date"] = (today - timedelta(days=1)).isoformat()
        else:  # restore: the member signs a new consent today
            current = {
                **current,
                "consent_id": f"SYN-CON-DEMO-{number:02d}",
                "granted_date": today.isoformat(),
                "expires_date": None,
                "revoked_date": None,
                "source": "re-signed consent form",
            }
            records.append(current)
    return json.dumps(records, indent=2) + "\n"


def snapshot_content(settings: Settings, state: DemoState, feed: str, today: date) -> str:
    base = _base_file(settings, feed)
    if feed == "consents":
        return _consents(base, state.consent_events, today)
    return _csv_with_rows(base, state.extra_rows.get(feed, []))


def write_inbox_file(
    settings: Settings, state: DemoState, folder: str, name: str, content: str
) -> Path:
    state.deliveries += 1
    path = settings.demo_inbox_dir / f"{state.deliveries:03d}" / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def refresh_downstream(session: Session, clock: Clock) -> list[int]:
    """Everything after ingest. Returns the ids of tasks resolved by the new data."""
    run_matching(session, clock)  # a member new to this feed needs a link before any Fact
    run_normalisation(session)
    refresh_facts(session, clock)
    score_members(session, clock)
    return [t.id for t in resolve_tasks_by_data(session, clock)]


def deliver(
    session: Session, settings: Settings, state: DemoState, feed: str, clock: Clock
) -> Load | None:
    """Ingest a fresh snapshot of `feed`, or hold it if the feed is paused."""
    folder, stem = SNAPSHOTS[feed]
    if folder in state.paused_feeds:
        if folder not in state.held_feeds:
            state.held_feeds.append(folder)
        return None
    today = clock.now().astimezone(PLAN_TZ).date()
    content = snapshot_content(settings, state, feed, today)
    path = write_inbox_file(settings, state, folder, f"{stem}_{today:%Y%m%d}.{_ext(stem)}", content)
    return ingest_file(session, path, clock=clock, landing_root=demo_landing(settings))


def demo_landing(settings: Settings) -> Path:
    """Landing area for demo deliveries: wiped on Reset, unlike the build's landing area."""
    return settings.demo_inbox_dir / "landing"


def _ext(stem: str) -> str:
    return "json" if stem == "consents" else "csv"


def bad_pharmacy_file(settings: Settings, state: DemoState, today: date) -> Path:
    """A pharmacy file whose layout changed upstream (a renamed column): must be quarantined."""
    text = _base_file(settings, "pharmacy").read_text(encoding="utf-8")
    header, rest = text.split("\n", 1)
    return write_inbox_file(
        settings,
        state,
        "pharmacy",
        f"pharmacy_ncpdp_{today:%Y%m%d}.csv",
        header.replace("ndc,", "ndc_code,", 1) + "\n" + rest,
    )
