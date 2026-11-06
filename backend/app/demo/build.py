"""`make demo` build: a fresh demo database, frozen at the reference instant.

migrate -> synth -> ingest -> identity -> normalise -> facts -> users -> signals and scores,
then the demo state file, a pristine copy of the database (for Reset) and a queue snapshot.
Deterministic: the same build twice gives byte-identical queue output.
"""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session

from app.core.clock import REFERENCE_INSTANT, FixedClock
from app.core.config import Settings
from app.datalayer_mock.identity import run_matching
from app.datalayer_mock.ingest import ingest_all
from app.datalayer_mock.normalise.run import run_normalisation
from app.db.session import create_db_engine, create_session_factory
from app.demo.state import DemoState, save_state
from app.facts import refresh_facts
from app.scoring.service import score_members
from app.synth.generate import generate
from app.workbench.seed import seed_workbench
from app.workbench.views import build_queue

BACKEND_DIR = Path(__file__).resolve().parents[2]
T = TypeVar("T")


def sqlite_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise ValueError("demo mode runs on a SQLite file (DATABASE_URL=sqlite:///...)")
    return Path(url.database)


def migrate(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def queue_snapshot(session: Session, clock: FixedClock) -> dict[str, Any]:
    queue = build_queue(session, clock, scope="all", user=None)
    return queue.model_dump(mode="json")


def copy_sqlite(source: Path, target: Path) -> None:
    """Consistent copy with the SQLite backup API (safe while other connections are open)."""
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def build(
    settings: Settings,
    *,
    log: Callable[[str], None] = print,
    background_members: int = 0,
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    clock = FixedClock(REFERENCE_INSTANT)
    started = time.perf_counter()

    def step(name: str, action: Callable[[], T]) -> T:
        began = time.perf_counter()
        result = action()
        elapsed = time.perf_counter() - began
        if timings is not None:
            timings[name] = elapsed
        log(f"  {name:<24} {elapsed:5.1f} s")
        return result

    db_file = sqlite_path(settings.database_url)
    for stale in (db_file, Path(f"{db_file}-wal"), Path(f"{db_file}-shm")):
        stale.unlink(missing_ok=True)  # drop the database
    db_file.parent.mkdir(parents=True, exist_ok=True)

    step("migrate", lambda: migrate(settings.database_url))
    step("synth", lambda: generate(settings.raw_dir, background_members=background_members))
    engine: Engine = create_db_engine(settings.database_url)
    try:
        with create_session_factory(engine)() as session:
            step(
                "ingest",
                lambda: ingest_all(
                    session, settings.raw_dir, clock=clock, landing_root=settings.landing_dir
                ),
            )
            step("identity", lambda: run_matching(session, clock))
            step("normalise", lambda: run_normalisation(session))
            step("facts", lambda: refresh_facts(session, clock))
            step("users", lambda: seed_workbench(session, clock))
            step("signals and scores", lambda: score_members(session, clock))
            session.commit()
            snapshot = queue_snapshot(session, clock)
    finally:
        engine.dispose()

    save_state(settings, DemoState())
    copy_sqlite(db_file, settings.demo_pristine_db)
    text = json.dumps(snapshot, indent=2, sort_keys=True)
    (settings.data_dir / "queue_snapshot.json").write_text(text + "\n", encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    log(f"  built in {time.perf_counter() - started:.1f} s; queue sha256 {digest}")
    for row in snapshot["rows"][:5]:
        log(f"  #{row['rank']} {row['member_id']} {row['tier']} {row['score']}")
    return snapshot
