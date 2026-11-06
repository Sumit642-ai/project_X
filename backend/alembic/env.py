from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.ai_draft.models  # noqa: F401
import app.datalayer_mock.identity.models  # noqa: F401
import app.datalayer_mock.ingest.models  # noqa: F401  (register tables on Base.metadata)
import app.datalayer_mock.ingest.staging  # noqa: F401
import app.datalayer_mock.normalise.models  # noqa: F401
import app.encounters.models  # noqa: F401
import app.facts.models  # noqa: F401
import app.scoring.models  # noqa: F401
import app.signals.models  # noqa: F401
import app.workbench.models  # noqa: F401
import app.writeback.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# An explicit sqlalchemy.url (e.g. set by tests) wins; otherwise use app settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
