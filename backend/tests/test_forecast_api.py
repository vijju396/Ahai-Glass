"""Forecast generation and retrieval contracts.

Generation itself refits models over the real panel and is exercised out of band
(`docs/STATUS.md` Phase 9). These cover the request contracts and the
data-honesty properties that must hold whatever the numbers are:

- submission returns 202 and refuses to start without an active champion,
- a scope with no forecast is a **row that says why**, with a null point
  forecast rather than a zero,
- `point <= q80 <= q90 <= q95` on every served row,
- the reconciliation adjustment is a separate field, and the method - including
  a fallback - is on the row,
- the hierarchy response re-checks coherence from the persisted rows rather than
  echoing the run's own flag,
- lineage resolves from a forecast row back to its model run and champion
  selection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import session_scope
from app.models.champions import ChampionSelection
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, TrainingRun

_PERIODS = ["2026-08", "2026-09", "2026-10", "2026-11", "2026-12", "2027-01"]


def _training(with_champion: bool = True) -> tuple[str, str, str | None]:
    """A completed training run, optionally with an active champion."""
    with session_scope() as db:
        dataset = Dataset(name="Forecast fixture", source_label="source")
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
        prep = PreprocessingRun(
            mapping_id=mapping.id, status="completed", progress_pct=100.0
        )
        db.add(prep)
        db.flush()
        build = PanelBuild(
            preprocessing_run_id=prep.id,
            status="completed",
            progress_pct=100.0,
            period_count=28,
            series_count=68_675,
            artifacts_json={"panel": "/tmp/panel.parquet"},
        )
        db.add(build)
        db.flush()
        run = TrainingRun(
            panel_build_id=build.id,
            status="completed",
            tiers="aggregate",
            min_history_profile="reference",
            xgboost_training_profile="fast",
            max_local_series=0,
        )
        db.add(run)
        db.flush()

        model_run = ModelRun(
            training_run_id=run.id,
            tier="aggregate",
            scope_level="national",
            scope_key="NATIONAL",
            model_id="var_exog",
            display_name="VAR with exogenous variables",
            status="completed",
            evaluation_mode="rolling_origin",
            wape=4.578,
            mae=7558.0,
            bias=1.1,
            validation_points=10,
        )
        db.add(model_run)
        db.flush()

        selection_id = None
        if with_champion:
            selection = ChampionSelection(
                training_run_id=run.id,
                scope_kind="overall",
                scope_key="NATIONAL",
                evaluated_scope_level="national",
                champion_model_id="var_exog",
                champion_display_name="VAR with exogenous variables",
                champion_model_run_id=model_run.id,
                champion_wape=4.578,
                selection_source="automatic",
                is_active=True,
            )
            db.add(selection)
            db.flush()
            selection_id = selection.id
        return run.id, model_run.id, selection_id


def _forecast_run(
    *,
    training_run_id: str,
    model_run_id: str | None = None,
    selection_id: str | None = None,
    status: str = "completed",
    with_unavailable: bool = False,
    coherent: bool = True,
    fallback: bool = False,
    with_partial_series: bool = False,
) -> str:
    """A completed forecast run with national, region and branch rows."""
    with session_scope() as db:
        training = db.get(TrainingRun, training_run_id)
        run = ForecastRun(
            training_run_id=training_run_id,
            panel_build_id=training.panel_build_id,
            status=status,
            progress_pct=100.0 if status == "completed" else 40.0,
            origin_period="2026-07",
            horizons="1,2,3,4,5,6",
            requested_reconciliation="mint_shrinkage",
            reconciliation_method="bottom_up" if fallback else "mint_shrinkage",
            reconciliation_fallback_from="mint_shrinkage" if fallback else None,
            reconciliation_fallback_reason=(
                "Only 3 residual rows available; 5 are required."
                if fallback
                else None
            ),
            coherent=coherent,
            max_incoherence=0.0 if coherent else 512.0,
            quantile_crossings_corrected=2,
            summary_json={
                "origin_period": "2026-07",
                "forecast_periods": _PERIODS,
                "reconciliation": {
                    "base_level": "branch",
                    "partial_levels": ["series"] if with_partial_series else [],
                },
            },
        )
        db.add(run)
        db.flush()
        run_id = run.id

        for index, period in enumerate(_PERIODS, start=1):
            branch_a = 60_000.0 + index * 100
            branch_b = 40_000.0 + index * 50
            for level, key, value in (
                ("branch", "JAIPUR", branch_a),
                ("branch", "MUMBAI", branch_b),
                ("region", "NORTH-1", branch_a),
                ("region", "WEST", branch_b),
                ("national", "NATIONAL", branch_a + branch_b),
            ):
                db.add(
                    ForecastRow(
                        forecast_run_id=run_id,
                        scope_level=level,
                        scope_key=key,
                        canonical_branch=key if level == "branch" else None,
                        region=key if level == "region" else None,
                        demand_segment="smooth",
                        period=period,
                        horizon=index,
                        model_id="var_exog",
                        model_display_name="VAR with exogenous variables",
                        model_run_id=model_run_id,
                        champion_selection_id=selection_id,
                        forecast_source="champion",
                        point_forecast=value,
                        q80=value * 1.08,
                        q90=value * 1.14,
                        q95=value * 1.21,
                        base_forecast=value - 250.0,
                        reconciliation_adjustment=250.0,
                        reconciliation_method=(
                            "bottom_up" if fallback else "mint_shrinkage"
                        ),
                        quantile_method="conformal",
                        quantile_pooling_level="model_horizon_segment",
                        quantile_residual_count=42,
                        target_source="order",
                        is_censored=False,
                        drivers_json={"seasonal_period": None, "history_months": 28},
                    )
                )

        if with_partial_series:
            # Two series against a network of thousands: a deliberate top-N
            # subset, so its total is not expected to match the branch level.
            for index, period in enumerate(_PERIODS, start=1):
                for key in ("JAIPUR|SKU1", "JAIPUR|SKU2"):
                    db.add(
                        ForecastRow(
                            forecast_run_id=run_id,
                            scope_level="series",
                            scope_key=key,
                            canonical_branch="JAIPUR",
                            canonical_sku=key.split("|")[1],
                            period=period,
                            horizon=index,
                            model_id="lstm",
                            point_forecast=500.0,
                            q80=540.0,
                            q90=570.0,
                            q95=605.0,
                            base_forecast=500.0,
                            reconciliation_adjustment=0.0,
                            reconciliation_method="none",
                        )
                    )

        if with_unavailable:
            for index, period in enumerate(_PERIODS, start=1):
                db.add(
                    ForecastRow(
                        forecast_run_id=run_id,
                        scope_level="branch",
                        scope_key="MANDI",
                        period=period,
                        horizon=index,
                        model_id="sarimax",
                        unavailable_reason=(
                            "The champion 'sarimax' is not eligible on this "
                            "scope's full history: needs 24 observations, has 11."
                        ),
                    )
                )
        return run_id


@pytest.fixture()
def no_job_submission(monkeypatch: pytest.MonkeyPatch):
    submitted: list[str] = []

    class _Runner:
        def submit(self, job_id, kind, fn, *args, **kwargs):  # noqa: ANN001, ANN002
            submitted.append(job_id)
            return None

        def is_running(self, job_id) -> bool:  # noqa: ANN001
            return job_id in submitted

    monkeypatch.setattr(
        "app.services.forecast_service.get_runner", lambda: _Runner()
    )
    return submitted


class TestGeneration:
    def test_it_returns_202_without_forecasting_in_the_request(
        self, client, no_job_submission
    ) -> None:
        training_id, _model_run, _selection = _training()
        response = client.post("/api/forecasts/runs", json={})
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["training_run_id"] == training_id
        assert body["horizons"] == "1,2,3,4,5,6"
        assert no_job_submission == [body["id"]]

    def test_it_refuses_to_start_without_an_active_champion(
        self, client, no_job_submission
    ) -> None:
        """Without a champion there is no model to forecast with, and picking
        one silently would be an invention."""
        _training(with_champion=False)
        response = client.post("/api/forecasts/runs", json={})
        assert response.status_code == 404
        assert "champion" in response.json()["error"]["message"].lower()

    def test_a_second_concurrent_run_is_refused(self, client, no_job_submission) -> None:
        _training()
        assert client.post("/api/forecasts/runs", json={}).status_code == 202
        response = client.post("/api/forecasts/runs", json={})
        assert response.status_code == 409
        assert "already in progress" in response.json()["error"]["message"]

    def test_an_unknown_reconciliation_method_is_refused_with_the_valid_set(
        self, client, no_job_submission
    ) -> None:
        _training()
        response = client.post(
            "/api/forecasts/runs", json={"reconciliation": "telepathy"}
        )
        assert response.status_code == 422
        assert "mint_shrinkage" in response.text

    def test_an_empty_horizon_list_is_refused(self, client, no_job_submission) -> None:
        _training()
        response = client.post("/api/forecasts/runs", json={"horizons": [0, -1]})
        assert response.status_code == 422

    def test_a_failed_run_reports_its_own_failure(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            status="failed",
        )
        body = client.get(f"/api/forecasts/runs/{run_id}").json()
        assert body["status"] == "failed"

    def test_no_completed_run_is_a_404_pointing_at_generation(self, client) -> None:
        response = client.get("/api/forecasts/runs/current")
        assert response.status_code == 404
        assert "POST /api/forecasts/runs" in response.json()["error"]["remediation"]


class TestQuerying:
    def test_rows_cover_six_horizons_for_a_scope(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts",
            params={"scope_level": "national", "scope_key": "NATIONAL"},
        ).json()
        assert body["total"] == 6
        assert [row["horizon"] for row in body["items"]] == [1, 2, 3, 4, 5, 6]
        assert [row["period"] for row in body["items"]] == _PERIODS

    def test_the_quantile_ordering_holds_on_every_row(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        rows = client.get("/api/forecasts", params={"limit": 500}).json()["items"]
        served = [row for row in rows if row["point_forecast"] is not None]
        assert served
        for row in served:
            assert row["point_forecast"] <= row["q80"] <= row["q90"] <= row["q95"]

    def test_the_reconciliation_adjustment_is_a_separate_field(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        row = client.get(
            "/api/forecasts", params={"scope_level": "national"}
        ).json()["items"][0]
        assert row["base_forecast"] is not None
        assert row["reconciliation_adjustment"] == pytest.approx(250.0)
        assert row["point_forecast"] == pytest.approx(
            row["base_forecast"] + row["reconciliation_adjustment"]
        )
        assert row["reconciliation_method"] == "mint_shrinkage"

    def test_the_interval_provenance_travels_on_the_row(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        row = client.get("/api/forecasts").json()["items"][0]
        assert row["quantile_method"] == "conformal"
        assert row["quantile_pooling_level"] == "model_horizon_segment"
        assert row["quantile_residual_count"] == 42

    def test_lineage_resolves_back_to_the_model_run_and_selection(
        self, client
    ) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        row = client.get("/api/forecasts").json()["items"][0]
        assert row["model_run_id"] == model_run
        assert row["champion_selection_id"] == selection
        assert row["forecast_source"] == "champion"

    def test_the_target_source_travels_with_the_forecast(self, client) -> None:
        """A forecast fitted through a sales-proxy window is not the same claim
        as one fitted on ordered quantity."""
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        row = client.get("/api/forecasts").json()["items"][0]
        assert row["target_source"] == "order"
        assert row["is_censored"] is False

    def test_rows_can_be_filtered_by_period_range(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts",
            params={
                "scope_level": "national",
                "period_from": "2026-09",
                "period_to": "2026-11",
            },
        ).json()
        assert [row["period"] for row in body["items"]] == [
            "2026-09",
            "2026-10",
            "2026-11",
        ]

    def test_rows_can_be_filtered_by_model(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_unavailable=True,
        )
        body = client.get("/api/forecasts", params={"model_id": "sarimax"}).json()
        assert body["total"] == 6
        assert all(row["model_id"] == "sarimax" for row in body["items"])


class TestUnavailableRows:
    def test_a_scope_with_no_forecast_is_a_row_that_says_why(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_unavailable=True,
        )
        body = client.get(
            "/api/forecasts", params={"scope_key": "MANDI"}
        ).json()
        assert body["total"] == 6
        for row in body["items"]:
            assert row["point_forecast"] is None, "a zero would look like real demand"
            assert row["q95"] is None
            assert "not eligible" in row["unavailable_reason"]

    def test_unavailable_rows_are_included_by_default(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_unavailable=True,
        )
        default = client.get("/api/forecasts", params={"limit": 500}).json()
        assert any(row["unavailable_reason"] for row in default["items"])

    def test_they_can_be_excluded_explicitly(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_unavailable=True,
        )
        filtered = client.get(
            "/api/forecasts", params={"include_unavailable": False, "limit": 500}
        ).json()
        assert filtered["total"] == 30
        assert all(row["point_forecast"] is not None for row in filtered["items"])


class TestSeriesView:
    def test_it_returns_the_horizons_metrics_and_drivers(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts/series",
            params={"scope_level": "national", "scope_key": "NATIONAL"},
        ).json()
        assert len(body["forecasts"]) == 6
        assert body["origin_period"] == "2026-07"
        assert body["validation_metrics"]["model_id"] == "var_exog"
        assert body["validation_metrics"]["wape"] == pytest.approx(4.578)
        assert body["drivers"]["history_months"] == 28
        assert body["snapshot_caveat"]

    def test_the_metrics_are_the_champions_own_not_recomputed(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get("/api/forecasts/series").json()
        assert body["validation_metrics"]["evaluation_mode"] == "rolling_origin"
        assert body["validation_metrics"]["validation_points"] == 10

    def test_an_unknown_scope_is_a_404(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        response = client.get(
            "/api/forecasts/series", params={"scope_key": "ATLANTIS"}
        )
        assert response.status_code == 404


class TestHierarchy:
    def test_level_totals_are_returned_bottom_up(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"period": "2026-08"}
        ).json()
        levels = [level["scope_level"] for level in body["levels"]]
        assert levels == ["branch", "region", "national"]

    def test_coherence_is_rechecked_from_the_persisted_rows(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"period": "2026-08"}
        ).json()
        assert body["level_gaps"]
        for gap in body["level_gaps"]:
            assert gap["coherent"] is True
            assert gap["difference"] == pytest.approx(0.0, abs=1e-6)

    def test_an_incoherent_run_is_reported_as_incoherent(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            coherent=False,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"forecast_run_id": run_id}
        ).json()
        assert body["coherent"] is False
        assert body["max_incoherence"] == pytest.approx(512.0)

    def test_a_reconciliation_fallback_is_named_with_its_reason(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            fallback=True,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"forecast_run_id": run_id}
        ).json()
        assert body["reconciliation_method"] == "bottom_up"
        assert body["reconciliation_fallback_from"] == "mint_shrinkage"
        assert "5 are required" in body["reconciliation_fallback_reason"]

    def test_the_adjustment_total_is_exposed_per_level(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"period": "2026-08"}
        ).json()
        national = next(
            level for level in body["levels"] if level["scope_level"] == "national"
        )
        assert national["adjustment_total"] == pytest.approx(250.0)
        assert national["point_total"] == pytest.approx(
            national["base_total"] + national["adjustment_total"]
        )

    def test_crossings_corrected_are_surfaced_not_silent(self, client) -> None:
        training_id, model_run, selection = _training()
        _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        body = client.get("/api/forecasts/hierarchy").json()
        assert body["quantile_crossings_corrected"] == 2


class TestPartialLevels:
    """A level finer than the reconciliation base is a subset of the network.

    Regression for a real defect: `LEVEL_ORDER` picked `series` as the base
    whenever any series row existed, so a run including the top-N local tier
    reconciled a 100-series hierarchy and overwrote the full-network branch
    aggregates with subtotals of the sampled part. Branch and region totals
    then disagreed by 37,794 units while the run still reported
    `coherent: true`.
    """

    def test_a_partial_level_is_not_reported_as_incoherent(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_partial_series=True,
        )
        body = client.get(
            "/api/forecasts/hierarchy",
            params={"forecast_run_id": run_id, "period": "2026-08"},
        ).json()
        gap = next(
            item for item in body["level_gaps"] if item["from_level"] == "series"
        )
        # The totals genuinely differ, and that is expected rather than a fault.
        assert gap["coherent"] is False
        assert gap["expected_coherent"] is False
        assert "subset of the network" in gap["reason"]

    def test_the_reconciled_levels_are_still_held_to_coherence(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_partial_series=True,
        )
        body = client.get(
            "/api/forecasts/hierarchy",
            params={"forecast_run_id": run_id, "period": "2026-08"},
        ).json()
        for gap in body["level_gaps"]:
            if gap["from_level"] == "series":
                continue
            assert gap["expected_coherent"] is True
            assert gap["coherent"] is True, gap

    def test_the_base_level_and_partial_levels_are_reported(self, client) -> None:
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
            with_partial_series=True,
        )
        body = client.get(
            "/api/forecasts/hierarchy", params={"forecast_run_id": run_id}
        ).json()
        assert body["reconciliation_base_level"] == "branch"
        assert body["partial_levels"] == ["series"]

    def test_a_genuine_disagreement_is_still_called_a_defect(self, client) -> None:
        """A gap between two levels that *were* reconciled together must not be
        excused as an expected subset."""
        training_id, model_run, selection = _training()
        run_id = _forecast_run(
            training_run_id=training_id,
            model_run_id=model_run,
            selection_id=selection,
        )
        with session_scope() as db:
            row = (
                db.query(ForecastRow)
                .filter(
                    ForecastRow.forecast_run_id == run_id,
                    ForecastRow.scope_level == "national",
                    ForecastRow.period == "2026-08",
                )
                .one()
            )
            row.point_forecast = (row.point_forecast or 0.0) + 5_000.0
        body = client.get(
            "/api/forecasts/hierarchy",
            params={"forecast_run_id": run_id, "period": "2026-08"},
        ).json()
        gap = next(
            item for item in body["level_gaps"] if item["to_level"] == "national"
        )
        assert gap["coherent"] is False
        assert gap["expected_coherent"] is True
        assert "defect" in gap["reason"]


class TestPiiExclusion:
    def test_no_forecast_field_can_carry_pii(self) -> None:
        from app.domain.ais.source_spec import ALL_PII_COLUMNS
        from app.schemas.forecasts import ForecastRowOut, ForecastRunOut

        forbidden = {name.lower().replace(" ", "_") for name in ALL_PII_COLUMNS}
        fields = set(ForecastRowOut.model_fields) | set(ForecastRunOut.model_fields)
        assert not (fields & forbidden)
