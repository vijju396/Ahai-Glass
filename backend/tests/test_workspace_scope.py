"""One location question, one answer, on every page.

Before this, three screens answered it three ways. Demand Analytics read the
panel and showed 53 branches. The Model Leaderboard read a training run and
showed whichever branches that run had reached. Supply Intelligence read the
branch dimension and showed 57 depots. Nothing said why they disagreed.

The tests here cover the two halves of the fix: `WorkspaceScope`, which decides
and applies the restriction, and `resolve_run`, which decides *which* run the
restriction is read from - because a run cancelled at 88% used to silently
become the authority for the whole application.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.core.config import get_settings
from app.db.session import session_scope
from app.domain.ais.workspace import (
    SOURCE_SETTING,
    SOURCE_TRAINING_RUN,
    SOURCE_UNRESTRICTED,
    UNRESTRICTED,
    WorkspaceScope,
    resolve_workspace,
)
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, TrainingRun
from app.services import champion_service

BRANCH_COL = "canonical_branch"


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            BRANCH_COL: ["AHMEDABAD", "BENGALURU", "CHENNAI", "DELHI-1"],
            "target": [10, 20, 30, 40],
        }
    )


def _scope(*branches: str) -> WorkspaceScope:
    return WorkspaceScope(
        branches=branches or None, source=SOURCE_SETTING, detail="test", total_branches=53
    )


# ----------------------------------------------------------------------
# Applying a scope
# ----------------------------------------------------------------------


def test_it_keeps_only_the_workspace_branches():
    kept = _scope("AHMEDABAD", "BENGALURU").restrict(_frame(), BRANCH_COL)

    assert sorted(kept[BRANCH_COL]) == ["AHMEDABAD", "BENGALURU"]


def test_it_matches_branch_names_case_insensitively():
    kept = _scope("ahmedabad").restrict(_frame(), BRANCH_COL)

    assert list(kept[BRANCH_COL]) == ["AHMEDABAD"]


def test_an_unrestricted_scope_changes_nothing():
    frame = _frame()

    assert UNRESTRICTED.restrict(frame, BRANCH_COL) is frame
    assert UNRESTRICTED.is_restricted is False
    assert UNRESTRICTED.note() is None


def test_a_frame_with_no_branch_axis_passes_through_untouched():
    """Not every frame on the way to a screen has a branch column.

    Raising here would break a page for a restriction that does not apply to
    it, which is a worse outcome than not restricting something with no
    branches to restrict.
    """
    frame = pd.DataFrame({"period": ["2026-01"], "target": [1]})

    assert _scope("AHMEDABAD").restrict(frame, BRANCH_COL) is frame


def test_a_restricted_scope_always_carries_a_note_naming_what_it_covers():
    note = _scope("AHMEDABAD", "BENGALURU").note()

    assert note is not None
    assert "2 of 53 branches" in note
    assert "AHMEDABAD, BENGALURU" in note
    # The load-bearing half: a KPI over two branches must not read as national.
    assert "not the national network" in note


def test_the_payload_says_restricted_false_rather_than_omitting_the_key():
    """A client must be able to tell "everything" from "narrowed"."""
    payload = UNRESTRICTED.as_dict()

    assert payload["restricted"] is False
    assert payload["branches"] is None
    assert payload["source"] == SOURCE_UNRESTRICTED


def test_it_reports_a_caller_filter_that_falls_outside_the_workspace():
    scope = _scope("AHMEDABAD", "BENGALURU")

    assert scope.allows("BENGALURU") is True
    assert scope.allows("bengaluru") is True
    assert scope.allows("CHENNAI") is False
    assert scope.allows(None) is True
    assert UNRESTRICTED.allows("CHENNAI") is True


def test_keep_filters_a_list_and_preserves_its_order():
    scope = _scope("BENGALURU", "AHMEDABAD")

    assert scope.keep(["DELHI-1", "BENGALURU", "CHENNAI", "AHMEDABAD"]) == [
        "BENGALURU",
        "AHMEDABAD",
    ]


# ----------------------------------------------------------------------
# Resolving a scope
# ----------------------------------------------------------------------


@pytest.fixture
def clear_settings():
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_session():
    """A session on the isolated test database, committed on exit.

    The conftest `_clean_tables` fixture empties every table afterwards, so
    rows written here do not leak into the next test.
    """
    with session_scope() as session:
        yield session


def test_the_setting_wins_over_the_training_run(db_session, monkeypatch, clear_settings):
    monkeypatch.setenv("AIS_WORKSPACE_BRANCHES", '["SURAT","RAJKOT"]')
    get_settings.cache_clear()

    scope = resolve_workspace(db_session)

    assert scope.source == SOURCE_SETTING
    assert scope.branches == ("SURAT", "RAJKOT")


def _panel_build(db) -> str:
    """The dataset -> version -> mapping -> preprocessing -> panel chain.

    A training run's `panel_build_id` is a real foreign key, so the chain has
    to exist even for a test that only cares about run resolution.
    """
    dataset = Dataset(name="Workspace fixture", source_label="source")
    db.add(dataset)
    db.flush()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=1,
        status=IngestionStatus.COMPLETED,
        progress_pct=100.0,
    )
    db.add(version)
    db.flush()
    mapping = MappingVersion(
        dataset_version_id=version.id,
        version_number=1,
        state="confirmed",
        confirmed_at=datetime.now(timezone.utc),
        confirmed_by="planner",
    )
    db.add(mapping)
    db.flush()
    prep = PreprocessingRun(mapping_id=mapping.id, status="completed", progress_pct=100.0)
    db.add(prep)
    db.flush()
    build = PanelBuild(
        preprocessing_run_id=prep.id,
        status="completed",
        progress_pct=100.0,
        training_cut_period="2025-09",
        period_count=28,
    )
    db.add(build)
    db.flush()
    return build.id


def _run(db, *, status: str, minutes: int, branches: list[str] | None) -> TrainingRun:
    run = TrainingRun(
        panel_build_id=_panel_build(db),
        status=status,
        tiers="aggregate",
        min_history_profile="reference",
        xgboost_training_profile="fast",
        max_local_series=10,
        created_at=datetime(2026, 9, 10, tzinfo=timezone.utc) + timedelta(minutes=minutes),
        restriction_json=(
            {"branches_matched": branches, "applied": True} if branches else None
        ),
    )
    db.add(run)
    db.flush()
    db.add(
        ModelRun(
            training_run_id=run.id,
            model_id="auto_arima",
            display_name="Auto ARIMA",
            tier="aggregate",
            scope_level="national",
            scope_key="NATIONAL",
            status="completed",
        )
    )
    db.flush()
    return run


def test_it_reads_the_branches_off_the_active_training_run(db_session):
    _run(db_session, status="completed", minutes=0, branches=["AHMEDABAD", "BENGALURU"])

    scope = resolve_workspace(db_session)

    assert scope.source == SOURCE_TRAINING_RUN
    assert scope.branches == ("AHMEDABAD", "BENGALURU")


def test_an_unrestricted_run_means_every_branch(db_session):
    _run(db_session, status="completed", minutes=0, branches=None)

    assert resolve_workspace(db_session).is_restricted is False


def test_a_finished_run_outranks_a_newer_cancelled_one(db_session):
    """The regression that made the whole application look national again.

    A run cancelled at 88% keeps every row it wrote - deliberately, nothing is
    discarded. But those rows cover whichever scopes the tier happened to reach
    first, so letting the partial sweep outrank a completed run silently
    changed which branches every page appeared to cover.
    """
    scoped = _run(
        db_session, status="completed_with_warnings", minutes=0, branches=["AHMEDABAD"]
    )
    _run(db_session, status="cancelled", minutes=30, branches=None)

    assert champion_service.resolve_run(db_session, None).id == scoped.id
    assert resolve_workspace(db_session).branches == ("AHMEDABAD",)


def test_a_cancelled_run_is_still_the_authority_when_nothing_finished(db_session):
    """Falling back matters: an error would be worse than a partial board."""
    partial = _run(db_session, status="cancelled", minutes=0, branches=None)

    assert champion_service.resolve_run(db_session, None).id == partial.id


def test_a_cancelled_run_is_still_reachable_by_id(db_session):
    _run(db_session, status="completed", minutes=0, branches=["AHMEDABAD"])
    cancelled = _run(db_session, status="cancelled", minutes=30, branches=None)

    assert champion_service.resolve_run(db_session, cancelled.id).id == cancelled.id


def test_with_total_records_how_many_branches_are_being_left_out():
    scope = WorkspaceScope(
        branches=("AHMEDABAD",), source=SOURCE_SETTING, detail="test"
    ).with_total(53)

    assert scope.total_branches == 53
    assert "1 of 53 branches" in (scope.note() or "")
