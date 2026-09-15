"""Alembic environment.

The URL and target metadata come from the application's own settings and ORM
registry, so a migration can never be generated against a different schema
than the one the app uses.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.logging import logging_is_configured
from app.db.base import Base
import app.models  # noqa: F401 - registers every table on Base.metadata

config = context.config

# Logging, and why this is guarded twice.
#
# `fileConfig` defaults to `disable_existing_loggers=True`, which sets
# `.disabled = True` on every logger that is not named in alembic.ini, and
# replaces the root handlers with alembic's stderr console at WARNING. When
# the app calls `ensure_schema()` inside its lifespan, that killed
# `uvicorn.error` and `app.*` for the rest of the process - so uvicorn's
# "[Errno 10048] only one usage of each socket address" never reached the
# terminal and the server appeared to exit in silence (docs/DECISIONS.md
# D-047).
#
# 1. Skip it entirely when the application already owns logging.
# 2. When alembic *is* the CLI entry point and does own logging, still refuse
#    to disable other loggers. Silencing a library is a formatting choice;
#    disabling it is a way to lose an error.
if config.config_file_name is not None and not logging_is_configured():
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Fall back to the application settings, but never override a URL a caller
# already put on the Config. Overwriting it would send a programmatic
# `command.upgrade` against the app database instead of the one requested -
# which is exactly what tests and one-off migrations need to control.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Required for SQLite: it cannot ALTER most columns in place.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
