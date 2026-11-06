import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FixedClock
from app.db.session import create_db_engine, create_session_factory
from app.main import create_app
from app.scoring.models import MemberScore

BACKEND_DIR = Path(__file__).resolve().parents[1]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live", action="store_true", help="run tests marked live (they call the real API)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="calls the real Anthropic API; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite file migrated to head once per session; tests get their own copy."""
    path = tmp_path_factory.mktemp("db") / "template.db"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "head")
    return path


@pytest.fixture
def session(migrated_template: Path, tmp_path: Path) -> Iterator[Session]:
    db_path = tmp_path / "test.db"
    shutil.copyfile(migrated_template, db_path)
    engine = create_db_engine(f"sqlite:///{db_path}")
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    return tmp_path / "landing"


@pytest.fixture(scope="session")
def generated_raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """data/raw as `make synth` writes it, generated once per test session."""
    from app.synth.generate import generate

    out = tmp_path_factory.mktemp("raw")
    generate(out)
    return out


@pytest.fixture(scope="session")
def ingested_template(
    migrated_template: Path, generated_raw: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Migrated DB with all generated feeds ingested at the reference clock, built once."""
    from app.datalayer_mock.ingest import ingest_all

    work = tmp_path_factory.mktemp("ingested")
    path = work / "ingested.db"
    shutil.copyfile(migrated_template, path)
    engine = create_db_engine(f"sqlite:///{path}")
    with create_session_factory(engine)() as db_session:
        ingest_all(db_session, generated_raw, clock=FixedClock(), landing_root=work / "landing")
    engine.dispose()
    return path


@pytest.fixture
def ingested(ingested_template: Path, tmp_path: Path) -> Iterator[Session]:
    """A session on a private copy of the ingested database."""
    db_path = tmp_path / "ingested.db"
    shutil.copyfile(ingested_template, db_path)
    engine = create_db_engine(f"sqlite:///{db_path}")
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture(scope="session")
def facts_template(ingested_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ingested + matched; a nurse has confirmed SYN-001-H -> SYN-001; Facts built."""
    from sqlalchemy import select

    from app.datalayer_mock.identity import confirm_link, run_matching
    from app.datalayer_mock.identity.models import MemberLink
    from app.facts import refresh_facts

    path = tmp_path_factory.mktemp("facts") / "facts.db"
    shutil.copyfile(ingested_template, path)
    engine = create_db_engine(f"sqlite:///{path}")
    clock = FixedClock()
    with create_session_factory(engine)() as db_session:
        run_matching(db_session, clock)
        link = db_session.scalars(
            select(MemberLink).where(MemberLink.source_record_id == "SYN-001-H")
        ).one()
        confirm_link(db_session, link.id, "maria.cm", clock=clock)
        refresh_facts(db_session, clock)
        db_session.commit()
    engine.dispose()
    return path


@pytest.fixture
def facts_db(facts_template: Path, tmp_path: Path) -> Iterator[Session]:
    db_path = tmp_path / "facts.db"
    shutil.copyfile(facts_template, db_path)
    engine = create_db_engine(f"sqlite:///{db_path}")
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture(scope="session")
def morning_template(ingested_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The 08:00 state on 2026-11-09: matched, nothing confirmed yet, Facts built."""
    from app.datalayer_mock.identity import run_matching
    from app.facts import refresh_facts

    path = tmp_path_factory.mktemp("morning") / "morning.db"
    shutil.copyfile(ingested_template, path)
    engine = create_db_engine(f"sqlite:///{path}")
    clock = FixedClock()
    with create_session_factory(engine)() as db_session:
        run_matching(db_session, clock)
        refresh_facts(db_session, clock)
        db_session.commit()
    engine.dispose()
    return path


@pytest.fixture
def morning(morning_template: Path, tmp_path: Path) -> Iterator[Session]:
    db_path = tmp_path / "morning.db"
    shutil.copyfile(morning_template, db_path)
    engine = create_db_engine(f"sqlite:///{db_path}")
    with create_session_factory(engine)() as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def scores(morning: Session) -> dict[str, MemberScore]:
    """Signals and scores for every member at the reference clock."""
    from app.scoring.service import score_members

    return {row.member_id: row for row in score_members(morning, FixedClock())}
