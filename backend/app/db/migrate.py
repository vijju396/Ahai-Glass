"""Schema management at startup.

Alembic owns the schema (docs/DECISIONS.md D-006). This module makes that true
in practice without requiring a manual `alembic upgrade head` on a fresh clone,
and without breaking a database that predates the baseline revision.

Three cases, all handled explicitly:

1. **Empty database** - run every migration.
2. **Already Alembic-managed** - upgrade to head.
3. **Tables exist but no `alembic_version`** - created by an earlier
   `create_all`, before the baseline revision existed. Such a database cannot
   simply be stamped: it may be missing tables the baseline adds, and stamping
   would assert a schema it does not have. It also cannot simply be upgraded,
   because re-running `CREATE TABLE` on the tables it *does* have would fail.
   So the missing tables are created with `checkfirst=True` and the database is
   then stamped at head. That adopts a real ingestion instead of destroying it,
   and it runs once - afterwards the database is Alembic-managed like any other.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import engine

logger = get_logger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def head_revision() -> str | None:
    config = _alembic_config()
    return ScriptDirectory.from_config(config).get_current_head()


def current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def ensure_schema() -> dict[str, str | None]:
    """Bring the database to the head revision. Returns what it did."""
    config = _alembic_config()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    stamped = "alembic_version" in tables
    has_app_tables = bool(tables - {"alembic_version"})

    if has_app_tables and not stamped:
        # Pre-baseline database. Create only what is missing, then stamp - a
        # bare stamp would claim tables that do not exist, and a bare upgrade
        # would fail on the ones that do.
        import app.models  # noqa: F401 - registers every table
        from app.db.base import Base

        before = set(tables)
        Base.metadata.create_all(bind=engine, checkfirst=True)
        created = sorted(set(inspect(engine).get_table_names()) - before)
        command.stamp(config, "head")
        action = "adopted_pre_baseline_schema"
        if created:
            logger.warning(
                "schema_adopted_with_missing_tables_created",
                extra={"created_tables": created},
            )
    else:
        command.upgrade(config, "head")
        action = "upgraded"

    # Drift check. A database can claim head and still be missing tables the
    # head revision declares - that is exactly what an over-eager stamp
    # produces, and the symptom is a bare "no such table" on the first query.
    # Repair it and say so loudly rather than let it surface as a 500.
    repaired = _repair_missing_tables()
    if repaired:
        action = f"{action}_with_drift_repair"

    resolved = current_revision()
    logger.info(
        "schema_ready",
        extra={
            "action": action,
            "revision": resolved,
            "head": head_revision(),
            "tables_repaired": repaired or None,
        },
    )
    return {
        "action": action,
        "revision": resolved,
        "head": head_revision(),
        "tables_repaired": ",".join(repaired) if repaired else None,
    }


def _repair_missing_tables() -> list[str]:
    """Create any declared table the database is missing. Returns their names."""
    import app.models  # noqa: F401 - registers every table
    from app.db.base import Base

    present = set(inspect(engine).get_table_names())
    missing = sorted(set(Base.metadata.tables) - present)
    if not missing:
        return []
    logger.warning(
        "schema_drift_detected",
        extra={
            "missing_tables": missing,
            "detail": (
                "The database reports the head revision but does not contain these "
                "tables. Creating them now. Investigate how the revision was applied "
                "- a stamp without a migration is the usual cause."
            ),
        },
    )
    Base.metadata.create_all(bind=engine, checkfirst=True)
    return missing
