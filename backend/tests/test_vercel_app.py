"""The Vercel entry (vercel_app.py) starts from the bundled demo data with no configuration,
serves the API with or without the /api prefix, and writes back through the in-process mock CM.
Runs in a subprocess so its environment defaults do not leak into the rest of the suite."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import vercel_app
from fastapi.testclient import TestClient

out = {}
with TestClient(vercel_app.app) as c:
    out["health_api"] = c.get("/api/health").json()
    out["health"] = c.get("/health").json()
    out["config"] = c.get("/api/demo/config").json()["demo_mode"]
    token = c.post("/api/auth/login", json={"username": "maria"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    out["first"] = c.get("/api/queue", headers=h).json()["rows"][0]["member_id"]
    link = c.get("/api/members/SYN-001/360", headers=h).json()["pending_links"][0]["id"]
    c.post(f"/api/members/SYN-001/links/{link}/confirm", headers=h)
    call = {"member_id": "SYN-001", "number": "555-0142"}
    eid = c.post("/api/encounters", json=call, headers=h).json()["id"]
    c.post(f"/api/encounters/{eid}/verify-identity", headers=h)
    c.post(f"/api/encounters/{eid}/wrap-up", json={"notes": "Reached Raymond."}, headers=h)
    meds = ("loop_diuretic", "hf_therapy", "beta_blocker", "discharge_med_list",
            "supply_on_hand", "pharmacy")
    for f in meds:
        body = {"time_on_field_ms": 3000}
        c.post(f"/api/encounters/{eid}/fields/{f}/confirm", json=body, headers=h)
    out["save"] = c.post(f"/api/encounters/{eid}/save", headers=h).json()["status"]
print("RESULT " + json.dumps(out))
"""


@pytest.mark.skipif(
    not (BACKEND / "deploy" / "demo-data" / "demo.db").is_file(),
    reason="no Vercel bundle: run make vercel-bundle",
)
def test_the_vercel_entry_runs_the_demo_end_to_end(tmp_path: Path) -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"DATA_DIR", "DATABASE_URL", "DEMO_MODE", "APP_ENV", "MOCK_CM_URL"}
    }
    env["CASECOMPASS_RUNTIME_DIR"] = str(tmp_path / "runtime")
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(BACKEND)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, result.stderr[-2000:]
    out = json.loads(line.removeprefix("RESULT "))
    assert out == {
        "health_api": {"status": "ok"},
        "health": {"status": "ok"},
        "config": True,
        "first": "SYN-001",
        "save": "synced",
    }
    assert (tmp_path / "runtime" / "mock_cm.db").is_file()  # written back in process
