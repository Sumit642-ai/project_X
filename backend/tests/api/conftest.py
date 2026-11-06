import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import Clock, FixedClock, get_clock
from app.db.session import create_db_engine, create_session_factory, get_db
from app.main import create_app
from app.writeback.client import CmClient, get_cm_client
from mock_cm.app import create_app as create_mock_cm


@pytest.fixture(scope="session")
def api_template(morning_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The demo database as `make seed` leaves it: users, assignments, signals, scores."""
    from app.scoring.service import score_members
    from app.workbench.seed import seed_workbench

    path = tmp_path_factory.mktemp("api") / "api.db"
    shutil.copyfile(morning_template, path)
    engine = create_db_engine(f"sqlite:///{path}")
    with create_session_factory(engine)() as session:
        seed_workbench(session, FixedClock())
        score_members(session, FixedClock())
        session.commit()
    engine.dispose()
    return path


class Api:
    def __init__(
        self,
        client: TestClient,
        factory: Callable[[], Session],
        set_clock: Callable[[Clock], None],
        cm: TestClient,
        app: FastAPI,
    ) -> None:
        self.client = client
        self.app = app  # for dependency overrides (settings, the AI draft model)
        self.session = factory
        self._set_clock = set_clock
        self.cm = cm  # the mock CM platform (set modes, inspect entries)
        self._tokens: dict[object, dict[str, str]] = {}

    def set_clock(self, clock: Clock) -> None:
        self._tokens.clear()  # tokens are checked against the clock: sign in again
        self._set_clock(clock)

    def token_key(self, username: str) -> object:
        return username

    def as_(self, username: str) -> dict[str, str]:
        """Sign in once per user (sign-in is rate limited) and reuse the token."""
        key = self.token_key(username)
        if key not in self._tokens:
            response = self.client.post("/auth/login", json={"username": username})
            assert response.status_code == 200, response.text
            self._tokens[key] = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return self._tokens[key]


@pytest.fixture
def api(api_template: Path, tmp_path: Path) -> Iterator[Api]:
    db_path = tmp_path / "api.db"
    shutil.copyfile(api_template, db_path)
    # TestClient serves requests on another thread, so SQLite must allow that.
    engine = create_db_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    factory = create_session_factory(engine)
    clock: list[Clock] = [FixedClock()]

    def db() -> Iterator[Session]:
        with factory() as session:
            yield session

    mock_cm = TestClient(create_mock_cm(f"sqlite:///{tmp_path / 'mock_cm.db'}"))
    app = create_app()
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_clock] = lambda: clock[0]
    app.dependency_overrides[get_cm_client] = lambda: CmClient(mock_cm)
    with TestClient(app) as client:
        yield Api(client, factory, lambda c: clock.__setitem__(0, c), mock_cm, app)
    engine.dispose()
