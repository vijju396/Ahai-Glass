"""Training orchestration contracts.

A real run over the aggregate tier takes minutes and the pooled tier tens of
minutes, so the job itself is exercised end to end out of band
(`docs/STATUS.md` Phase 7). What is asserted here is everything a request can
be held to without doing the work:

- submission returns 202 and does not block,
- the estimate stored on the run is the estimate that was returned,
- a second concurrent run is refused rather than queued behind the first,
- no model can vanish from the per-model listing, and `models_missing` says so
  when one has,
- status is never a filter parameter,
- cancellation keeps the rows already written,
- the SSE stream terminates on a terminal state instead of hanging.
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import session_scope
from app.ml.registry.canonical_models import (
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
    MODEL_DISPLAY_NAMES,
)
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, QuantileCalibration, TrainingRun


def _panel_build(
    status: str = "completed",
    *,
    period_count: int = 28,
    series_count: int = 68_675,
) -> str:
    """A completed panel build with the real panel's measured shape."""
    with session_scope() as db:
        dataset = Dataset(name="Training fixture", source_label="source")
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
        run = PreprocessingRun(
            mapping_id=mapping.id,
            status="completed",
            progress_pct=100.0,
            artifacts_json={"order_fact": "/tmp/order_fact.parquet"},
        )
        db.add(run)
        db.flush()
        build = PanelBuild(
            preprocessing_run_id=run.id,
            status=status,
            progress_pct=100.0 if status == "completed" else 30.0,
            training_cut_period="2025-09",
            horizons="1,2,3,4,5,6",
            panel_rows=1_510_850,
            series_count=series_count,
            period_count=period_count,
            training_rows=900_000,
            scoring_rows=412_050,
            feature_count=41,
            artifacts_json={"panel": "/tmp/panel.parquet"},
            summary_json={"aggregate_scope_count": 69},
        )
        db.add(build)
        db.flush()
        return build.id


@pytest.fixture()
def no_job_submission(monkeypatch: pytest.MonkeyPatch):
    """Stop the route launching a multi-hour run, and record what it asked for."""
    submitted: list[str] = []

    class _Runner:
        def submit(self, job_id, kind, fn, *args, **kwargs):  # noqa: ANN001, ANN002
            submitted.append(job_id)
            return None

        def is_running(self, job_id) -> bool:  # noqa: ANN001
            return job_id in submitted

        def cancel(self, job_id) -> bool:  # noqa: ANN001
            return True

    monkeypatch.setattr(
        "app.services.training.training_service.get_runner", lambda: _Runner()
    )
    return submitted


def _seed_model_runs(
    run_id: str,
    *,
    model_ids=CANONICAL_MODEL_IDS,
    tier: str = "aggregate",
    scope_level: str = "national",
    scope_key: str = "NATIONAL",
    include_baselines: bool = True,
) -> None:
    """One row per model, deliberately spanning every terminal status."""
    statuses = [
        "completed",
        "ineligible",
        "failed",
        "timed_out",
        "not_evaluated_budget",
    ]
    display = dict(MODEL_DISPLAY_NAMES)
    with session_scope() as db:
        for index, model_id in enumerate(model_ids):
            status = statuses[index % len(statuses)]
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    tier=tier,
                    scope_level=scope_level,
                    scope_key=scope_key,
                    model_id=model_id,
                    display_name=display.get(model_id, model_id),
                    is_baseline=False,
                    status=status,
                    evaluation_mode="rolling_origin",
                    failure_reason=None if status == "completed" else f"{status} reason",
                    wape=0.4 + index / 100 if status == "completed" else None,
                    mae=10.0 + index if status == "completed" else None,
                    origins_completed=2 if status == "completed" else 0,
                    origins_total=2,
                    validation_points=12 if status == "completed" else 0,
                )
            )
        if include_baselines:
            for baseline in BASELINE_METHOD_IDS:
                db.add(
                    ModelRun(
                        training_run_id=run_id,
                        tier=tier,
                        scope_level=scope_level,
                        scope_key=scope_key,
                        model_id=baseline,
                        display_name=baseline,
                        is_baseline=True,
                        status="completed",
                        evaluation_mode="rolling_origin",
                        wape=0.35,
                        mae=9.0,
                        origins_completed=2,
                        origins_total=2,
                        validation_points=12,
                    )
                )


class TestEstimate:
    def test_it_costs_the_run_without_starting_it(self, client, no_job_submission) -> None:
        build_id = _panel_build()
        response = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["aggregate"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["estimated_seconds"] > 0
        assert body["estimated_seconds_upper"] >= body["estimated_seconds"]
        assert body["tiers"][0]["tier"] == "aggregate"
        assert body["tiers"][0]["fits"] > 0
        assert "measured in this project" in body["provenance"]
        # Nothing was submitted.
        assert no_job_submission == []
        with session_scope() as db:
            assert db.query(TrainingRun).count() == 0

    def test_the_upper_bound_is_stated_in_human_terms(self, client) -> None:
        build_id = _panel_build()
        body = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["aggregate", "local"]},
        ).json()
        assert body["estimated_human"]
        assert body["estimated_human_upper"]
        assert {tier["tier"] for tier in body["tiers"]} == {"aggregate", "local"}

    def test_pre_emption_is_off_by_default_and_opt_in_per_run(self, client) -> None:
        """Measured in Phase 7: a fresh interpreter costs more than the fit it
        would protect, for all thirteen. So the default is empty on purpose and
        the caller opts in."""
        build_id = _panel_build()
        default = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["aggregate"]},
        ).json()
        assert default["hard_timeout_models"] == []

        opted_in = client.post(
            "/api/training/estimate",
            json={
                "panel_build_id": build_id,
                "tiers": ["aggregate"],
                "hard_timeout_models": ["auto_arima", "lstm"],
            },
        ).json()
        assert opted_in["hard_timeout_models"] == ["auto_arima", "lstm"]
        assert opted_in["estimated_seconds"] >= default["estimated_seconds"]

    def test_an_unknown_tier_is_rejected_with_the_valid_set(self, client) -> None:
        build_id = _panel_build()
        response = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["magic"]},
        )
        assert response.status_code == 422
        assert "aggregate" in response.text

    def test_an_incomplete_panel_build_is_refused(self, client) -> None:
        build_id = _panel_build(status="running")
        response = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["aggregate"]},
        )
        assert response.status_code == 409
        assert "not completed" in response.json()["error"]["message"]

    def test_an_unknown_build_is_a_structured_404(self, client) -> None:
        response = client.post(
            "/api/training/estimate",
            json={"panel_build_id": "nope", "tiers": ["aggregate"]},
        )
        assert response.status_code == 404
        assert "nope" in response.json()["error"]["message"]


class TestSubmission:
    def test_it_returns_202_and_a_run_id_without_working(
        self, client, no_job_submission
    ) -> None:
        build_id = _panel_build()
        response = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["tiers"] == "aggregate"
        assert no_job_submission == [body["id"]]

    def test_the_estimate_shown_is_the_estimate_stored(
        self, client, no_job_submission
    ) -> None:
        """The number the caller saw must be the number that can be audited
        against `duration_seconds` later."""
        build_id = _panel_build()
        preview = client.post(
            "/api/training/estimate",
            json={"panel_build_id": build_id, "tiers": ["aggregate"]},
        ).json()
        submitted = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        ).json()
        # The stored figure is full precision; the displayed one is rounded to
        # a tenth of a second. They must not differ by more than that rounding.
        assert submitted["estimated_seconds"] == pytest.approx(
            preview["estimated_seconds"], abs=0.05
        )
        assert submitted["estimate"]["estimated_seconds"] == pytest.approx(
            preview["estimated_seconds"], abs=1e-9
        )
        assert submitted["estimate"]["hard_timeout_models"] == preview[
            "hard_timeout_models"
        ]

    def test_tiers_are_stored_in_execution_order_not_request_order(
        self, client, no_job_submission
    ) -> None:
        build_id = _panel_build()
        body = client.post(
            "/api/training",
            json={"panel_build_id": build_id, "tiers": ["pooled", "aggregate"]},
        ).json()
        assert body["tiers"] == "aggregate,pooled"

    def test_it_defaults_to_the_newest_panel_build(self, client, no_job_submission) -> None:
        first = _panel_build()
        second = _panel_build()
        # Give the two builds distinct timestamps explicitly. `created_at`
        # defaults to `utcnow()`, and on this platform two inserts can land in
        # the same millisecond - which makes "newest" a genuine tie and this
        # assertion pass about two runs in three. A real build takes minutes,
        # so the ambiguity is an artefact of the fixture, not of the query.
        with session_scope() as db:
            db.get(PanelBuild, first).created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            db.get(PanelBuild, second).created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        body = client.post("/api/training", json={"tiers": ["aggregate"]}).json()
        assert body["panel_build_id"] == second

    def test_settings_supply_the_profiles_when_the_body_omits_them(
        self, client, no_job_submission
    ) -> None:
        build_id = _panel_build()
        body = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        ).json()
        assert body["min_history_profile"]
        assert body["xgboost_training_profile"]
        assert body["max_local_series"] > 0
        assert body["per_model_timeout_seconds"] > 0

    def test_a_second_concurrent_run_is_refused(self, client, no_job_submission) -> None:
        build_id = _panel_build()
        first = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        )
        assert first.status_code == 202
        second = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        )
        assert second.status_code == 409
        assert "already in progress" in second.json()["error"]["message"]

    def test_an_empty_tier_list_is_refused_with_the_valid_set(
        self, client, no_job_submission
    ) -> None:
        build_id = _panel_build()
        response = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": []}
        )
        assert response.status_code == 409
        assert "aggregate" in response.json()["error"]["remediation"]


class TestRunListing:
    def test_runs_are_listed_newest_first_and_paginated(self, client) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            for index in range(3):
                db.add(
                    TrainingRun(
                        panel_build_id=build_id,
                        status="completed",
                        tiers="aggregate",
                        min_history_profile="reference",
                        xgboost_training_profile="fast",
                        max_local_series=index,
                    )
                )
        body = client.get("/api/training", params={"limit": 2}).json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

    def test_current_returns_the_latest_run(self, client) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            db.add(
                TrainingRun(
                    panel_build_id=build_id,
                    status="completed",
                    tiers="aggregate,pooled",
                    min_history_profile="reference",
                    xgboost_training_profile="fast",
                    max_local_series=500,
                )
            )
        body = client.get("/api/training/current").json()
        assert body["tiers"] == "aggregate,pooled"

    def test_no_run_at_all_is_a_404_with_guidance_not_an_empty_body(
        self, client
    ) -> None:
        response = client.get("/api/training/current")
        assert response.status_code == 404
        assert "POST /api/training" in response.json()["error"]["remediation"]

    def test_an_unknown_run_is_a_structured_404(self, client) -> None:
        response = client.get("/api/training/does-not-exist")
        assert response.status_code == 404
        assert "does-not-exist" in response.json()["error"]["message"]


class TestNoModelDisappears:
    def _run(self) -> str:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
            )
            db.add(run)
            db.flush()
            return run.id

    def test_all_thirteen_appear_whatever_their_status(self, client) -> None:
        run_id = self._run()
        _seed_model_runs(run_id)
        body = client.get(f"/api/training/{run_id}").json()
        returned = [
            row["model_id"] for row in body["model_runs"] if not row["is_baseline"]
        ]
        assert sorted(returned) == sorted(CANONICAL_MODEL_IDS)
        assert body["models_missing"] == []

    def test_non_completed_statuses_are_present_and_carry_a_reason(
        self, client
    ) -> None:
        run_id = self._run()
        _seed_model_runs(run_id)
        rows = client.get(f"/api/training/{run_id}").json()["model_runs"]
        by_status = {row["status"] for row in rows if not row["is_baseline"]}
        assert {"ineligible", "failed", "timed_out", "not_evaluated_budget"} <= by_status
        for row in rows:
            if row["status"] != "completed":
                assert row["failure_reason"], row["model_id"]

    def test_a_missing_model_is_reported_rather_than_hidden(self, client) -> None:
        run_id = self._run()
        _seed_model_runs(run_id, model_ids=[m for m in CANONICAL_MODEL_IDS if m != "lstm"])
        body = client.get(f"/api/training/{run_id}").json()
        assert body["models_missing"] == ["lstm"]

    def test_status_is_not_an_available_filter(self, client) -> None:
        """Filtering by status is the caller's explicit decision to make on the
        rows, never a query parameter that can quietly drop the failures."""
        run_id = self._run()
        _seed_model_runs(run_id)
        response = client.get(f"/api/training/{run_id}", params={"status": "completed"})
        assert response.status_code == 200
        rows = response.json()["model_runs"]
        assert len({row["status"] for row in rows}) > 1

    def test_status_counts_cover_the_whole_run_not_the_returned_page(
        self, client
    ) -> None:
        run_id = self._run()
        _seed_model_runs(run_id)
        body = client.get(f"/api/training/{run_id}", params={"limit": 1}).json()
        assert body["model_runs_returned"] == 1
        assert sum(item["count"] for item in body["status_counts"]) == len(
            CANONICAL_MODEL_IDS
        ) + len(BASELINE_METHOD_IDS)
        assert body["models_missing"] == []

    def test_baselines_are_flagged_and_can_be_excluded_explicitly(
        self, client
    ) -> None:
        run_id = self._run()
        _seed_model_runs(run_id)
        page = client.get(
            f"/api/training/{run_id}/model-runs", params={"include_baselines": False}
        ).json()
        assert page["total"] == len(CANONICAL_MODEL_IDS)
        assert all(row["is_baseline"] is False for row in page["items"])
        withbase = client.get(f"/api/training/{run_id}/model-runs").json()
        assert withbase["total"] == len(CANONICAL_MODEL_IDS) + len(BASELINE_METHOD_IDS)
        assert {row["model_id"] for row in withbase["items"] if row["is_baseline"]} == set(
            BASELINE_METHOD_IDS
        )

    def test_rows_can_be_filtered_by_tier_and_scope(self, client) -> None:
        run_id = self._run()
        _seed_model_runs(run_id, tier="aggregate", scope_level="national")
        _seed_model_runs(
            run_id,
            tier="local",
            scope_level="series",
            scope_key="JAIPUR|ABC123",
            include_baselines=False,
        )
        national = client.get(
            f"/api/training/{run_id}/model-runs", params={"scope_level": "national"}
        ).json()
        series = client.get(
            f"/api/training/{run_id}/model-runs", params={"tier": "local"}
        ).json()
        assert national["total"] == len(CANONICAL_MODEL_IDS) + len(BASELINE_METHOD_IDS)
        assert series["total"] == len(CANONICAL_MODEL_IDS)
        assert {row["scope_key"] for row in series["items"]} == {"JAIPUR|ABC123"}

    def test_metrics_are_null_not_zero_when_undefined(self, client) -> None:
        """A NULL WAPE means undefined, which on this dataset is the common
        case. A zero would rank an unmeasured model first."""
        run_id = self._run()
        _seed_model_runs(run_id)
        rows = client.get(f"/api/training/{run_id}/model-runs").json()["items"]
        unfinished = [row for row in rows if row["status"] != "completed"]
        assert unfinished
        for row in unfinished:
            assert row["wape"] is None
            assert row["mae"] is None


class TestCalibrations:
    def test_cells_carry_their_pooling_provenance(self, client) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
            )
            db.add(run)
            db.flush()
            run_id = run.id
            db.add(
                QuantileCalibration(
                    training_run_id=run_id,
                    model_id="xgboost",
                    horizon=1,
                    segment="smooth",
                    residual_count=42,
                    offsets_json={
                        "q80": {
                            "offset": 3.2,
                            "method": "conformal",
                            "residual_count": 42,
                            "pooling_level": "model_horizon_segment",
                        }
                    },
                    pooling_level="model_horizon_segment",
                    method="conformal",
                )
            )
        body = client.get(f"/api/training/{run_id}/calibrations").json()
        assert body["total"] == 1
        cell = body["items"][0]
        assert cell["residual_count"] == 42
        assert cell["offsets"]["q80"]["pooling_level"] == "model_horizon_segment"
        assert cell["method"] == "conformal"

    def test_cells_can_be_filtered_by_model_and_horizon(self, client) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
            )
            db.add(run)
            db.flush()
            run_id = run.id
            for horizon in (1, 2):
                for model_id in ("xgboost", "sarimax"):
                    db.add(
                        QuantileCalibration(
                            training_run_id=run_id,
                            model_id=model_id,
                            horizon=horizon,
                            segment="all",
                            residual_count=10,
                            offsets_json={"q80": {"offset": 1.0}},
                        )
                    )
        assert (
            client.get(
                f"/api/training/{run_id}/calibrations", params={"model_id": "xgboost"}
            ).json()["total"]
            == 2
        )
        assert (
            client.get(
                f"/api/training/{run_id}/calibrations", params={"horizon": 2}
            ).json()["total"]
            == 2
        )


class TestCancellation:
    def _running_run(self) -> str:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
            )
            db.add(run)
            db.flush()
            return run.id

    def test_cancelling_moves_the_run_to_cancelling(self, client, no_job_submission) -> None:
        run_id = self._running_run()
        body = client.post(f"/api/training/{run_id}/cancel").json()
        assert body["status"] == "cancelling"
        assert body["stage_detail"]

    def test_cancelling_keeps_the_rows_already_written(
        self, client, no_job_submission
    ) -> None:
        run_id = self._running_run()
        _seed_model_runs(run_id)
        client.post(f"/api/training/{run_id}/cancel")
        page = client.get(f"/api/training/{run_id}/model-runs").json()
        assert page["total"] == len(CANONICAL_MODEL_IDS) + len(BASELINE_METHOD_IDS)

    def test_cancelling_a_finished_run_is_refused(self, client, no_job_submission) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
            )
            db.add(run)
            db.flush()
            run_id = run.id
        response = client.post(f"/api/training/{run_id}/cancel")
        assert response.status_code == 409
        assert "already" in response.json()["error"]["message"]


class TestProgressStream:
    def test_it_ends_on_a_terminal_state_rather_than_hanging(self, client) -> None:
        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="fast",
                max_local_series=0,
                progress_pct=100.0,
                stage_detail="Done",
                model_runs_total=17,
                model_runs_completed=9,
                model_runs_ineligible=5,
                model_runs_failed=2,
                model_runs_timed_out=1,
            )
            db.add(run)
            db.flush()
            run_id = run.id
        with client.stream(
            "GET", f"/api/training/{run_id}/events", params={"poll_seconds": 0.1}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())
        assert "event: progress" in body
        assert "event: end" in body
        assert '"model_runs_ineligible": 5' in body
        assert '"model_runs_failed": 2' in body

    def test_an_unknown_run_is_a_404_not_a_stream_of_errors(self, client) -> None:
        response = client.get("/api/training/nope/events")
        assert response.status_code == 404
        assert "nope" in response.json()["error"]["message"]


class TestPiiExclusion:
    def test_no_response_field_can_carry_pii(self, client) -> None:
        """The panel has no PII column, and the training payloads must not
        acquire one by accident."""
        from app.domain.ais.source_spec import ALL_PII_COLUMNS
        from app.schemas.training import ModelRunOut, TrainingRunSummary

        forbidden = {name.lower().replace(" ", "_") for name in ALL_PII_COLUMNS}
        fields = set(ModelRunOut.model_fields) | set(TrainingRunSummary.model_fields)
        assert not (fields & forbidden)

    def test_the_evaluation_column_list_excludes_pii(self) -> None:
        from app.domain.ais.source_spec import ALL_PII_COLUMNS
        from app.services.training.training_service import PANEL_COLUMNS

        forbidden = {name.lower().replace(" ", "_") for name in ALL_PII_COLUMNS}
        assert not (set(PANEL_COLUMNS) & forbidden)


class TestOrphanReconciliation:
    """A run whose owning process died must not keep saying `running`.

    The job runner is in-process, so a restart orphans anything in flight. The
    row is only ever written by the worker that owned it, so without startup
    reconciliation it says `running` forever and the UI shows a spinner for a
    run that will never finish. Found by inspecting the live database, where
    one such row was sitting.
    """

    def test_an_interrupted_run_is_marked_failed_with_a_reason(self):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
                started_at=datetime.now(timezone.utc),
            )
            db.add(run)
            db.flush()
            run_id = run.id

        assert reconcile_orphaned_runs() == 1

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            assert run.status == "failed"
            assert run.stage_detail == "Interrupted"
            assert run.finished_at is not None
            assert "server process ended" in run.failure_reason
            # The message must name the previous status, not the one just set.
            assert any("'running'" in w for w in (run.warnings_json or []))

    def test_reconciliation_keeps_the_rows_the_run_already_wrote(self):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
            )
            db.add(run)
            db.flush()
            db.add(
                ModelRun(
                    training_run_id=run.id,
                    tier="aggregate",
                    scope_level="national",
                    scope_key="NATIONAL",
                    model_id="sarimax",
                    display_name=MODEL_DISPLAY_NAMES["sarimax"],
                    status="completed",
                    wape=12.5,
                )
            )
            run_id = run.id

        reconcile_orphaned_runs()

        with session_scope() as db:
            rows = db.query(ModelRun).filter(ModelRun.training_run_id == run_id).all()
            assert len(rows) == 1, "partial evidence must survive reconciliation"
            assert rows[0].wape == 12.5
            run = db.get(TrainingRun, run_id)
            assert "1 model_run row(s)" in run.failure_reason

    def test_reconciliation_rebuilds_the_counters_from_the_stored_rows(self):
        """The row must not contradict itself.

        Only the owning worker writes the counters, at completion, so an
        orphaned run reported `model_runs_total = 0` while its own
        `failure_reason` on the same record said it had written thousands. The
        Training Center then showed "0 model runs" for a run that produced
        2,227 of them - measured on the real database, run 3c87a9ec.
        """
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        statuses = [
            ("completed", "sarimax", "NATIONAL"),
            ("completed", "auto_arima", "NATIONAL"),
            ("ineligible", "var", "NATIONAL"),
            ("failed", "lstm", "WEST"),
            ("timed_out", "xgboost", "WEST"),
            ("not_evaluated_budget", "exp_additive", "SOUTH-1"),
        ]
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
                started_at=datetime.now(timezone.utc),
            )
            db.add(run)
            db.flush()
            for status, model_id, scope_key in statuses:
                db.add(
                    ModelRun(
                        training_run_id=run.id,
                        tier="aggregate",
                        scope_level="national" if scope_key == "NATIONAL" else "region",
                        scope_key=scope_key,
                        model_id=model_id,
                        display_name=MODEL_DISPLAY_NAMES[model_id],
                        status=status,
                    )
                )
            run_id = run.id

        assert reconcile_orphaned_runs() == 1

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            assert run.model_runs_total == 6
            assert run.model_runs_completed == 2
            assert run.model_runs_ineligible == 1
            assert run.model_runs_failed == 1
            assert run.model_runs_timed_out == 1
            assert run.model_runs_not_evaluated == 1
            # Distinct (level, key) pairs, matching what completion counts -
            # six model rows over three scopes, not six scopes.
            assert run.series_evaluated == 3
            # The counters and the prose on the same row must agree.
            assert "6 model_run row(s)" in run.failure_reason
            assert "3 scope(s)" in run.failure_reason

    def test_reconciliation_computes_the_duration_it_already_has_both_ends_of(self):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        started = datetime.now(timezone.utc) - timedelta(minutes=11, seconds=28)
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
                started_at=started,
            )
            db.add(run)
            db.flush()
            run_id = run.id

        reconcile_orphaned_runs()

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            assert run.duration_seconds is not None
            # Both timestamps were already on the row; a null duration was a
            # subtraction nobody performed.
            assert 685 <= run.duration_seconds <= 700, run.duration_seconds

    def test_a_run_that_never_started_gets_no_invented_duration(self):
        """`queued` is reconciled too, and it has no start to measure from."""
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="queued",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
            )
            db.add(run)
            db.flush()
            run_id = run.id

        reconcile_orphaned_runs()

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            assert run.status == "failed"
            assert run.started_at is None
            assert run.duration_seconds is None

    def test_reconciliation_says_which_counters_it_could_not_recover(self):
        """`series_requested` and `residuals_recorded` came from memory.

        They died with the process. Leaving them at 0 is correct; leaving that
        silent would make them look like measurements.
        """
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
                started_at=datetime.now(timezone.utc),
            )
            db.add(run)
            db.flush()
            run_id = run.id

        reconcile_orphaned_runs()

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            assert run.series_requested == 0
            assert run.residuals_recorded == 0
            assert any(
                "not recoverable" in w for w in (run.warnings_json or [])
            ), run.warnings_json

    def test_reconciliation_does_not_promise_a_resume_it_cannot_deliver(self):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="running",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
            )
            db.add(run)
            db.flush()
            run_id = run.id

        reconcile_orphaned_runs()

        with session_scope() as db:
            reason = db.get(TrainingRun, run_id).failure_reason
            # It used to say "Resubmit the run to continue", which reads as a
            # resume. There is none - the stored rows are a record, not a
            # checkpoint, and a resubmission starts over.
            assert "no resume" in reason
            assert "from the start" in reason

    def test_a_finished_run_is_left_alone(self):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status="completed",
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
                duration_seconds=275.78,
            )
            db.add(run)
            db.flush()
            run_id = run.id

        assert reconcile_orphaned_runs() == 0
        with session_scope() as db:
            assert db.get(TrainingRun, run_id).status == "completed"
            assert db.get(TrainingRun, run_id).failure_reason is None

    @pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
    def test_every_live_status_is_reconciled(self, status: str):
        from app.services.training.training_service import reconcile_orphaned_runs

        build_id = _panel_build()
        with session_scope() as db:
            run = TrainingRun(
                panel_build_id=build_id,
                status=status,
                tiers="aggregate",
                min_history_profile="reference",
                xgboost_training_profile="thorough",
            )
            db.add(run)
            db.flush()
            run_id = run.id

        assert reconcile_orphaned_runs() == 1
        with session_scope() as db:
            assert db.get(TrainingRun, run_id).status == "failed"


class TestEstimateIsAudited:
    """The estimate must be comparable against the actual afterwards.

    `cost_model` exists so nobody starts a three-hour run by accident, and the
    run row keeps both numbers so the estimate can be checked rather than
    trusted. The summary was recording `estimated_seconds: 0.0` on every run -
    it read a config key that was never set - which made the comparison
    worthless while looking like it worked.
    """

    def test_the_run_row_stores_the_estimate_it_returned(
        self, client, no_job_submission
    ):
        build_id = _panel_build()
        response = client.post(
            "/api/training", json={"panel_build_id": build_id, "tiers": ["aggregate"]}
        )
        assert response.status_code == 202
        returned = response.json()["estimated_seconds"]
        assert returned and returned > 0

        with session_scope() as db:
            run = db.get(TrainingRun, response.json()["id"])
            assert run.estimated_seconds == pytest.approx(returned)

    def test_the_job_carries_the_estimate_into_its_summary(self):
        # The defect was that the job read `config["estimated"]`, a key nothing
        # ever wrote, so this value silently defaulted to 0.0.
        import inspect

        from app.services.training import training_service

        source = inspect.getsource(training_service._run_training_job)
        assert '"estimated_seconds": run.estimated_seconds' in source
        assert 'config.get("estimated", 0.0)' not in source

class TestScopeCounting:
    """The run's status counters must account for every row the run wrote.

    A run's counters are written once, at completion, from what `_evaluate_scope`
    returned - not recomputed from the rows. So a row that is persisted but not
    counted is invisible: it inflates `model_runs_total` without appearing under
    any status, and the Training Center shows a run whose parts do not sum to
    its whole.

    That is what happened. The baseline loop incremented `rows` but never
    `counts`, so run 9bc1c69c reported 833 total against 819 accounted for -
    196 baseline rows that had run, been stored, and then read as having
    silently disappeared. A full run takes minutes, so this asserts the
    structure rather than executing it.
    """

    def test_every_persisted_row_is_also_counted(self):
        import ast
        import inspect

        from app.services.training import training_service

        source = inspect.getsource(training_service._evaluate_scope)
        tree = ast.parse(textwrap.dedent(source))

        # Every `for` loop that persists a ModelRun must also touch `counts`.
        persisting_loops = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.For):
                continue
            body = ast.dump(node)
            if "ModelRun" not in body:
                continue
            persisting_loops += 1
            assert "counts" in body, (
                "A loop in _evaluate_scope persists a ModelRun without "
                "recording its status in `counts`. The row would exist in the "
                "database, be included in model_runs_total, and belong to no "
                "status - which is exactly how 196 baseline rows went missing."
            )

        # Registry models and baselines are written by two separate loops; if
        # that stops being true this test is checking less than it claims to.
        assert persisting_loops == 2, (
            f"Expected two persisting loops (registry, baselines), found "
            f"{persisting_loops}. Re-read this test before trusting it."
        )
