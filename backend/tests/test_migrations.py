"""Schema management: Alembic owns the schema, in all three start states.

The bug these guard: an earlier build created its tables with `create_all`, so
that database has application tables but no `alembic_version`. Stamping it at
head asserts a schema it does not have - the tables a later revision adds are
silently absent, and the first query against one fails with
`no such table`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.base import Base

EXPECTED_TABLES = {
    "dataset", "dataset_version", "source_file", "column_profile",
    "validation_control", "defect_record", "key_reconciliation",
    "mapping_version", "column_role_assignment", "mapping_rule_result",
    "preprocessing_run",
}

# Tables the Phase 2 build created, before the mapping tables existed.
PRE_BASELINE_TABLES = {
    "dataset", "dataset_version", "source_file", "column_profile",
    "validation_control", "defect_record", "key_reconciliation",
}


@pytest.fixture()
def scratch_db(tmp_path_factory) -> Path:
    directory = Path(__file__).resolve().parents[1].parent / "runtime" / "db"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "migration_probe.db"
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


def _ensure_against(path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run ensure_schema against a throwaway database file."""
    import app.db.migrate as migrate

    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    monkeypatch.setattr(migrate, "engine", engine)

    original = migrate._alembic_config

    def patched_config():
        config = original()
        config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
        return config

    monkeypatch.setattr(migrate, "_alembic_config", patched_config)
    try:
        return migrate.ensure_schema()
    finally:
        engine.dispose()


def _tables(path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


class TestFreshDatabase:
    def test_an_empty_database_is_migrated_to_head(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _ensure_against(scratch_db, monkeypatch)
        assert result["action"] == "upgraded"
        assert result["revision"] == result["head"]
        assert EXPECTED_TABLES <= _tables(scratch_db)

    def test_running_twice_is_a_no_op(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_against(scratch_db, monkeypatch)
        second = _ensure_against(scratch_db, monkeypatch)
        assert second["action"] == "upgraded"
        assert second["revision"] == second["head"]


class TestPreBaselineDatabase:
    def _make_pre_baseline(self, path: Path) -> None:
        """Recreate the Phase 2 situation: some tables, no alembic_version."""
        engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
        try:
            subset = [
                table for table in Base.metadata.sorted_tables
                if table.name in PRE_BASELINE_TABLES
            ]
            Base.metadata.create_all(bind=engine, tables=subset)
        finally:
            engine.dispose()

    def test_it_is_adopted_rather_than_stamped_blindly(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._make_pre_baseline(scratch_db)
        before = _tables(scratch_db)
        assert "mapping_version" not in before

        result = _ensure_against(scratch_db, monkeypatch)
        assert result["action"] == "adopted_pre_baseline_schema"
        assert result["revision"] == result["head"]

    def test_the_missing_tables_are_actually_created(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression. A bare stamp left mapping_version absent and the
        first mapping query failed with 'no such table'."""
        self._make_pre_baseline(scratch_db)
        _ensure_against(scratch_db, monkeypatch)
        after = _tables(scratch_db)
        assert EXPECTED_TABLES <= after
        assert "mapping_version" in after
        assert "column_role_assignment" in after
        assert "preprocessing_run" in after

    def test_pre_existing_data_survives_adoption(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adoption must never destroy a real ingestion to tidy the schema."""
        self._make_pre_baseline(scratch_db)
        engine = create_engine(f"sqlite:///{scratch_db.as_posix()}", future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO dataset (id, name, source_label, is_deleted, "
                        "created_at, updated_at) VALUES "
                        "('abc', 'Existing', 'source', 0, '2026-09-08', '2026-09-08')"
                    )
                )
        finally:
            engine.dispose()

        _ensure_against(scratch_db, monkeypatch)

        engine = create_engine(f"sqlite:///{scratch_db.as_posix()}", future=True)
        try:
            with engine.connect() as connection:
                rows = list(connection.execute(text("SELECT name FROM dataset")))
        finally:
            engine.dispose()
        assert [row[0] for row in rows] == ["Existing"]

    def test_a_second_run_takes_the_normal_upgrade_path(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._make_pre_baseline(scratch_db)
        _ensure_against(scratch_db, monkeypatch)
        second = _ensure_against(scratch_db, monkeypatch)
        assert second["action"] == "upgraded"


class TestRevisionIntegrity:
    def test_a_head_revision_exists(self) -> None:
        from app.db.migrate import head_revision

        assert head_revision()

    def test_the_migration_covers_every_orm_table(self, scratch_db: Path, monkeypatch) -> None:
        """A model added without a migration would pass every other test and
        then fail in production."""
        _ensure_against(scratch_db, monkeypatch)
        migrated = _tables(scratch_db) - {"alembic_version"}
        declared = set(Base.metadata.tables)
        assert declared - migrated == set(), f"Not created by migration: {declared - migrated}"


class TestDriftRepair:
    """A database can claim head and still lack tables the head revision
    declares - which is what an over-eager stamp produces. The symptom is a
    bare 'no such table' on the first query, so the drift is repaired and
    reported rather than left to surface as a 500.
    """

    def test_a_stamped_but_incomplete_schema_is_repaired(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        engine = create_engine(f"sqlite:///{scratch_db.as_posix()}", future=True)
        try:
            subset = [
                table for table in Base.metadata.sorted_tables
                if table.name in PRE_BASELINE_TABLES
            ]
            Base.metadata.create_all(bind=engine, tables=subset)
        finally:
            engine.dispose()

        # Stamp head without running the migration: the exact bad state.
        import app.db.migrate as migrate
        from alembic import command

        original = migrate._alembic_config

        def patched_config():
            config = original()
            config.set_main_option("sqlalchemy.url", f"sqlite:///{scratch_db.as_posix()}")
            return config

        monkeypatch.setattr(migrate, "_alembic_config", patched_config)
        command.stamp(patched_config(), "head")
        assert "mapping_version" not in _tables(scratch_db)

        result = _ensure_against(scratch_db, monkeypatch)
        assert "drift_repair" in result["action"]
        assert "mapping_version" in (result["tables_repaired"] or "")
        assert EXPECTED_TABLES <= _tables(scratch_db)

    def test_a_healthy_schema_reports_no_repair(
        self, scratch_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ensure_against(scratch_db, monkeypatch)
        second = _ensure_against(scratch_db, monkeypatch)
        assert second["tables_repaired"] is None
        assert "drift_repair" not in second["action"]
