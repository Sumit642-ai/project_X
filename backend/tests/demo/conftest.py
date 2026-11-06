"""A demo build (made once per session), copied per test, served with DEMO_MODE=true."""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.config import Settings, get_settings
from app.db.session import create_db_engine, create_session_factory, get_db
from app.demo.build import build
from app.demo.state import demo_clock, load_state
from app.main import create_app
from app.writeback.client import CmClient, get_cm_client
from mock_cm.app import create_app as create_mock_cm
from tests.api.conftest import Api


def demo_settings(data_dir: Path) -> Settings:
    return Settings(
        demo_mode=True,
        app_env="test",
        data_dir=data_dir,
        database_url=f"sqlite:///{(data_dir / 'demo.db').as_posix()}",
    )


@pytest.fixture(scope="session")
def demo_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    data_dir = tmp_path_factory.mktemp("demo_build")
    build(demo_settings(data_dir), log=lambda _line: None)
    return data_dir


class DemoApi(Api):
    settings: Settings

    def token_key(self, username: str) -> object:
        return (username, load_state(self.settings).instant)  # the demo clock moves

    def post(self, path: str, user: str = "janet") -> dict[str, object]:
        response = self.client.post(path, headers=self.as_(user))
        assert response.status_code < 400, response.text
        body: dict[str, object] = response.json()
        return body


@pytest.fixture
def demo(demo_template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[DemoApi]:
    data_dir = tmp_path / "demo"
    shutil.copytree(demo_template, data_dir, ignore=shutil.ignore_patterns("landing"))
    settings = demo_settings(data_dir)
    # Code outside the request (feed staleness, the draft model) reads the process settings,
    # as it does under `make demo`: set the same environment.
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    get_settings.cache_clear()
    engine = create_db_engine(settings.database_url, connect_args={"check_same_thread": False})
    factory = create_session_factory(engine)

    def db() -> Iterator[Session]:
        with factory() as session:
            yield session

    mock_cm = TestClient(create_mock_cm(f"sqlite:///{tmp_path / 'mock_cm.db'}"))
    app = create_app()
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_clock] = lambda: demo_clock(settings)
    app.dependency_overrides[get_cm_client] = lambda: CmClient(mock_cm)
    with TestClient(app) as client:
        api = DemoApi(client, factory, lambda c: None, mock_cm, app)
        api.settings = settings
        yield api
    engine.dispose()
    monkeypatch.undo()
    get_settings.cache_clear()
