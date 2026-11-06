from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db.session import create_db_engine, create_session_factory

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_session_factory_executes_query() -> None:
    factory = create_session_factory(create_db_engine("sqlite://"))

    with factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_alembic_upgrade_head_runs(tmp_path: Path) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migrate.db'}")

    command.upgrade(config, "head")
