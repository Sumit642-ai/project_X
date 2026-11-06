from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_db_engine(database_url: str, **kwargs: Any) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    # Local/demo SQLite: write-ahead log, and commit without waiting for a full disk flush.
    # Still crash-safe for the application; avoids slow fsyncs on every audited view.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@lru_cache
def get_engine() -> Engine:
    # Created lazily so importing the app never opens a database connection.
    return create_db_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
