"""`make perf`: performance at scale. Synthetic data only.

Builds a database with 5,000 background members (plus the five heroes), timing the nightly
pipeline (migrate, ingest, identity, normalise, facts, users, signals and scores; target under
10 minutes), then measures p95 latency of /queue and /members/{id}/360 in process (target under
300 ms). Writes data/perf/perf_report.json and exits non-zero if a target is missed.
"""

import json
import shutil
import statistics
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from app.core.clock import FixedClock, get_clock
from app.core.config import REPO_ROOT, Settings, get_settings
from app.db.session import create_db_engine, create_session_factory, get_db
from app.demo.build import build
from app.main import create_app

MEMBERS = 5000
SAMPLES = 60
P95_MS = 300.0
PIPELINE_MINUTES = 10.0
NIGHTLY = ("migrate", "ingest", "identity", "normalise", "facts", "users", "signals and scores")


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[18]


def measure(client: TestClient, path: str, headers: dict[str, str]) -> dict[str, Any]:
    client.get(path, headers=headers)  # warm up
    samples = []
    for _ in range(SAMPLES):
        began = time.perf_counter()
        response = client.get(path, headers=headers)
        samples.append((time.perf_counter() - began) * 1000)
        assert response.status_code == 200, response.text
    return {
        "path": path,
        "p95_ms": round(p95(samples), 1),
        "median_ms": round(statistics.median(samples), 1),
        "bytes": len(response.content),
    }


def main() -> int:
    data_dir = REPO_ROOT / "data" / "perf"
    shutil.rmtree(data_dir, ignore_errors=True)
    settings = Settings(
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'perf.db').as_posix()}",
        demo_mode=False,
    )
    print(f"Nightly pipeline with {MEMBERS:,} background members:")
    timings: dict[str, float] = {}
    build(settings, background_members=MEMBERS, timings=timings)
    nightly = sum(timings[step] for step in NIGHTLY)

    engine = create_db_engine(settings.database_url, connect_args={"check_same_thread": False})
    factory = create_session_factory(engine)
    with factory() as session:
        from sqlalchemy import func, select

        from app.datalayer_mock.identity.models import Member

        members = session.scalar(select(func.count()).select_from(Member)) or 0

    def db() -> Any:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_clock] = FixedClock
    app.dependency_overrides[get_settings] = lambda: settings
    results = []
    with TestClient(app) as client:

        def sign_in(username: str) -> dict[str, str]:
            body = client.post("/auth/login", json={"username": username}).json()
            return {"Authorization": f"Bearer {body['access_token']}"}

        maria, janet = sign_in("maria"), sign_in("janet")
        results.append(measure(client, "/queue", maria))
        results.append(measure(client, "/queue?cm=all", janet))
        results.append(measure(client, "/members/SYN-001/360", maria))
        results.append(measure(client, "/members/SYN-C057-020/360", janet))
    engine.dispose()

    passed = nightly / 60 < PIPELINE_MINUTES and all(r["p95_ms"] < P95_MS for r in results)
    report = {
        "members": members,
        "nightly_pipeline_seconds": round(nightly, 1),
        "steps_seconds": {k: round(v, 1) for k, v in timings.items()},
        "latency": results,
        "targets": {"p95_ms": P95_MS, "pipeline_minutes": PIPELINE_MINUTES},
        "passed": passed,
    }
    (data_dir / "perf_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nMembers in database: {members:,}")
    print(f"Nightly pipeline: {nightly:.1f} s (target < {PIPELINE_MINUTES:.0f} min)")
    for r in results:
        print(f"  {r['path']:<32} p95 {r['p95_ms']:6.1f} ms  median {r['median_ms']:6.1f} ms")
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
