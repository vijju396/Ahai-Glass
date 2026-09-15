"""Engine and session factory.

SQLite for the POC, with WAL enabled so a background training thread writing
progress does not block API reads. Everything above this module is engine-
agnostic: swapping `AIS_DATABASE_URL` to a PostgreSQL DSN needs no code change
(docs/DECISIONS.md-006).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()
_is_sqlite = _settings.database_url.startswith("sqlite")

if _is_sqlite:
    _settings.ensure_runtime_dirs()

engine: Engine = create_engine(
    _settings.database_url,
    echo=_settings.db_echo,
    future=True,
    # SQLite only: the job runner touches the DB from worker threads.
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
)


if _is_sqlite and _settings.sqlite_wal:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, expire_on_commit=False,
    class_=Session, future=True,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """For background jobs, which have no request lifecycle to hang off."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
