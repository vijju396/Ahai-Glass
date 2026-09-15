"""Monitoring, scenario, export and settings contracts.

The assertions concentrate on the distinctions these endpoints exist to keep:

- **"not computable" is not "no problem".** Error deterioration on this dataset
  cannot be measured at all, and the response has to say why rather than
  reporting zero deterioration.
- **A scenario never writes to its baseline.** The baseline rows are re-read
  after a scenario and must be byte-identical.
- **An export contains the rows the page showed**, including the ones with a
  reason instead of a number, and an undefined metric is an empty cell rather
  than a zero.
- **Settings publishes no connection string or filesystem path.**
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from app.db.session import session_scope
from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS
from app.models.champions import ChampionSelection
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, TrainingRun

_PERIODS = ["2026-08", "2026-09", "2026-10"]

#: Real parquet artifacts, written once. The monitoring and export paths read
#: the panel and the stock snapshot from disk, and pointing them at a
#: non-existent file would exercise the "artifact unavailable" branch instead of
#: the behaviour under test.
_ARTIFACTS = Path(tempfile.gettempdir()) / "ais_ops_fixture"


def _write_artifacts() -> dict[str, str]:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    panel_path = _ARTIFACTS / "panel.parquet"
    stock_path = _ARTIFACTS / "stock.parquet"

    # 28 months ending 2026-07, matching the real panel's span, so the
    # forecast periods (2026-08 onward) are genuinely unobserved.
    periods = [
        f"{2024 + (index + 3) // 12:04d}-{(index + 3) % 12 + 1:02d}"
        for index in range(28)
    ]
    panel = pd.DataFrame(
        {
            "period": periods * 2,
            "target": [100.0 + index for index in range(28)] * 2,
            "canonical_branch": ["JAIPUR"] * 28 + ["MANDI"] * 28,
            # The real panel's grain is branch x SKU x month, so this column
            # always exists. Omitting it here made the fixture unrealistic and
            # broke drift as soon as the workspace SKU restriction started
            # reading it (docs/DECISIONS.md D-056).
            "canonical_sku": ["SKU1"] * 28 + ["SKU2"] * 28,
            "target_source": ["order"] * 56,
        }
    )
    panel.to_parquet(panel_path, index=False)

    pd.DataFrame(
        {
            "canonical_branch": ["JAIPUR"],
            "canonical_sku": ["SKU1"],
            "usable_qty": [400.0],
            "closing_qty": [400.0],
            "has_negative_row": [False],
            "stock_class": ["Cat A"],
            "closing_value": [40_000.0],
        }
    ).to_parquet(stock_path, index=False)

    return {
        "panel": str(panel_path),
        "stock_position": str(stock_path),
    }


def _seed(*, with_forecast: bool = True, with_champion: bool = True) -> dict[str, str]:
    """A completed training run, champion and forecast run."""
    with session_scope() as db:
        dataset = Dataset(name="Ops fixture", source_label="source")
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
        artifacts = _write_artifacts()
        prep = PreprocessingRun(
            mapping_id=mapping.id,
            status="completed",
            progress_pct=100.0,
            artifacts_json={"stock_position": artifacts["stock_position"]},
        )
        db.add(prep)
        db.flush()
        build = PanelBuild(
            preprocessing_run_id=prep.id,
            status="completed",
            progress_pct=100.0,
            period_count=28,
            series_count=68_675,
            panel_rows=1_503_753,
            artifacts_json={"panel": artifacts["panel"]},
            summary_json={"last_period": "2026-07"},
        )
        db.add(build)
        db.flush()
        training = TrainingRun(
            panel_build_id=build.id,
            status="completed",
            tiers="aggregate",
            min_history_profile="reference",
            xgboost_training_profile="fast",
            max_local_series=0,
        )
        db.add(training)
        db.flush()

        model_run = ModelRun(
            training_run_id=training.id,
            tier="aggregate",
            scope_level="branch",
            scope_key="JAIPUR",
            model_id="var_exog",
            display_name="VAR with exogenous variables",
            status="completed",
            evaluation_mode="rolling_origin",
            wape=4.578,
            mae=7558.0,
            validation_points=10,
        )
        db.add(model_run)
        db.flush()

        ids = {"training": training.id, "model_run": model_run.id, "build": build.id}

        if with_champion:
            selection = ChampionSelection(
                training_run_id=training.id,
                scope_kind="branch",
                scope_key="JAIPUR",
                evaluated_scope_level="branch",
                champion_model_id="var_exog",
                champion_display_name="VAR with exogenous variables",
                champion_model_run_id=model_run.id,
                champion_wape=4.578,
                best_baseline_model_id="ma6",
                best_baseline_wape=9.939,
                beaten_by_baseline=False,
                selection_source="automatic",
                is_active=True,
            )
            db.add(selection)
            db.flush()
            ids["champion"] = selection.id

        if with_forecast:
            forecast = ForecastRun(
                training_run_id=training.id,
                panel_build_id=build.id,
                status="completed",
                progress_pct=100.0,
                origin_period="2026-07",
                horizons="1,2,3",
                requested_reconciliation="mint_variance",
                reconciliation_method="mint_variance",
                coherent=True,
                max_incoherence=0.0,
            )
            db.add(forecast)
            db.flush()
            ids["forecast"] = forecast.id
            for index, period in enumerate(_PERIODS, start=1):
                db.add(
                    ForecastRow(
                        forecast_run_id=forecast.id,
                        scope_level="branch",
                        scope_key="JAIPUR",
                        canonical_branch="JAIPUR",
                        period=period,
                        horizon=index,
                        model_id="var_exog",
                        model_display_name="VAR with exogenous variables",
                        model_run_id=model_run.id,
                        champion_selection_id=ids.get("champion"),
                        forecast_source="champion",
                        point_forecast=1000.0 * index,
                        q80=1080.0 * index,
                        q90=1140.0 * index,
                        q95=1210.0 * index,
                        base_forecast=1000.0 * index - 10,
                        reconciliation_adjustment=10.0,
                        reconciliation_method="mint_variance",
                        quantile_method="empirical",
                        quantile_pooling_level="scope_all_horizons",
                        quantile_residual_count=12,
                        target_source="order",
                        is_censored=False,
                    )
                )
                # One row with no forecast, so the "reason not a zero" rule can
                # be asserted through the export as well as the API.
                db.add(
                    ForecastRow(
                        forecast_run_id=forecast.id,
                        scope_level="branch",
                        scope_key="MANDI",
                        period=period,
                        horizon=index,
                        model_id="sarimax",
                        unavailable_reason=(
                            "The champion is not eligible on this scope's full "
                            "history: needs 24 observations, has 11."
                        ),
                    )
                )
        return ids


class TestMonitoring:
    def test_freshness_reports_demand_and_stock_ages_separately(self, client) -> None:
        """They are a month apart on this dataset, and collapsing them would
        hide why recommendations are current-snapshot estimates."""
        _seed()
        body = client.get("/api/monitoring").json()
        freshness = body["freshness"]
        assert freshness["demand_history_end"] == "2026-07"
        assert freshness["stock_snapshot_date"] == "2026-08-01"
        assert freshness["demand_history_age_months"] is not None
        assert freshness["stock_snapshot_age_months"] is not None
        assert "current-snapshot" in freshness["note"]

    def test_drift_compares_two_windows_and_applies_no_threshold(
        self, client
    ) -> None:
        _seed()
        drift = client.get("/api/monitoring").json()["drift"]
        assert drift["available"] is True
        assert drift["window_months"] == 6
        assert len(drift["recent_periods"]) == 6
        # Both window means are reported, so a reader can judge whether a shift
        # rests on a handful of months.
        assert drift["national"]["earlier"]["mean_monthly_demand"] is not None
        assert drift["national"]["recent"]["mean_monthly_demand"] is not None
        assert drift["national"]["shift_pct"] is not None
        assert "No threshold is applied" in drift["note"]

    def test_drift_flags_a_target_source_change_as_a_measurement_change(
        self, client
    ) -> None:
        """Part of any shift across a source change is a change of measurement
        rather than of demand, and the note has to say so."""
        _seed()
        drift = client.get("/api/monitoring").json()["drift"]
        # This fixture is order-sourced throughout, so nothing changed.
        assert drift["target_source_changed"] is False
        assert "same across both windows" in drift["note"]

    def test_drift_is_reported_per_branch(self, client) -> None:
        _seed()
        drift = client.get("/api/monitoring").json()["drift"]
        keys = {row["scope_key"] for row in drift["rows"]}
        assert {"JAIPUR", "MANDI"} <= keys

    def test_drift_is_unavailable_with_a_reason_when_the_panel_cannot_be_read(
        self, client
    ) -> None:
        _seed()
        with session_scope() as db:
            build = db.query(PanelBuild).first()
            build.artifacts_json = {"panel": "/nonexistent/panel.parquet"}
        drift = client.get("/api/monitoring").json()["drift"]
        assert drift["available"] is False
        assert drift["reason"]
        assert drift["rows"] == []

    def test_champion_age_counts_those_beaten_by_a_baseline(self, client) -> None:
        _seed()
        champions = client.get("/api/monitoring").json()["champions"]
        assert champions["active_champions"] == 1
        assert champions["champions_from_older_runs"] == 0
        assert champions["champions_beaten_by_a_baseline"] == 0
        assert champions["rows"][0]["champion_model_id"] == "var_exog"
        assert champions["rows"][0]["from_newest_training_run"] is True

    def test_deterioration_says_not_computable_rather_than_reporting_zero(
        self, client
    ) -> None:
        """The forecast origin is the last observed month, so no actual exists
        for any forecast period. Reporting no deterioration would claim a check
        that never happened."""
        _seed()
        deterioration = client.get("/api/monitoring").json()["deterioration"]
        assert deterioration["computable"] is False
        assert "has been observed" in deterioration["reason"]
        assert deterioration["rows"] == []

    def test_no_forecast_run_is_reported_rather_than_erroring(self, client) -> None:
        _seed(with_forecast=False)
        body = client.get("/api/monitoring").json()
        assert body["deterioration"]["computable"] is False
        assert "No completed forecast run" in body["deterioration"]["reason"]

    def test_nothing_raises_an_alert(self, client) -> None:
        """A page that decided what counts as a problem would hide the number
        that mattered."""
        body = client.get("/api/monitoring").json()
        assert "raises an alert" in body["note"]


class TestScenarios:
    def test_a_scenario_scales_demand_and_states_its_levers(self, client) -> None:
        _seed()
        body = client.post(
            "/api/scenarios",
            json={"name": "Peak", "demand_multiplier": 1.2, "scope_level": "branch"},
        ).json()
        assert body["name"] == "Peak"
        assert body["levers"]["demand_multiplier"] == 1.2
        assert body["totals"]["demand_delta_pct"] == pytest.approx(20.0)
        assert body["totals"]["scenario_demand"] == pytest.approx(
            body["totals"]["baseline_demand"] * 1.2
        )

    def test_the_quantile_scales_with_the_point_not_independently(self, client) -> None:
        """Scaling the point alone would leave an interval that no longer
        brackets it."""
        _seed()
        row = next(
            item
            for item in client.post(
                "/api/scenarios",
                json={"demand_multiplier": 2.0, "scope_level": "branch"},
            ).json()["rows"]
            if item["baseline_point"] is not None
        )
        assert row["scenario_point"] == pytest.approx(row["baseline_point"] * 2.0)
        assert row["scenario_quantile"] == pytest.approx(row["baseline_quantile"] * 2.0)
        assert row["scenario_quantile"] >= row["scenario_point"]

    def test_a_longer_lead_time_raises_the_order_without_changing_demand(
        self, client
    ) -> None:
        _seed()
        body = client.post(
            "/api/scenarios",
            json={"demand_multiplier": 1.0, "lead_time_days": 30, "scope_level": "branch"},
        ).json()
        assert body["totals"]["demand_delta"] == pytest.approx(0.0)
        assert body["totals"]["order_delta"] > 0

    def test_it_never_writes_to_the_baseline(self, client) -> None:
        ids = _seed()
        with session_scope() as db:
            before = [
                (row.id, row.point_forecast, row.q95)
                for row in db.query(ForecastRow)
                .filter(ForecastRow.forecast_run_id == ids["forecast"])
                .order_by(ForecastRow.id)
                .all()
            ]
        client.post(
            "/api/scenarios",
            json={"demand_multiplier": 3.0, "scope_level": "branch"},
        )
        with session_scope() as db:
            after = [
                (row.id, row.point_forecast, row.q95)
                for row in db.query(ForecastRow)
                .filter(ForecastRow.forecast_run_id == ids["forecast"])
                .order_by(ForecastRow.id)
                .all()
            ]
        assert before == after

    def test_a_scope_with_no_baseline_forecast_is_not_invented(self, client) -> None:
        _seed()
        rows = client.post(
            "/api/scenarios", json={"demand_multiplier": 1.5, "scope_level": "branch"}
        ).json()["rows"]
        refused = [row for row in rows if row["scope_key"] == "MANDI"]
        assert refused
        for row in refused:
            assert row["scenario_point"] is None
            assert row["unavailable_reason"]

    def test_an_absurd_multiplier_is_refused_with_its_bounds(self, client) -> None:
        _seed()
        response = client.post("/api/scenarios", json={"demand_multiplier": 100})
        assert response.status_code == 422
        assert "0.1" in response.text

    def test_an_unknown_service_level_is_refused(self, client) -> None:
        _seed()
        response = client.post("/api/scenarios", json={"service_level": 99})
        assert response.status_code == 422

    def test_a_level_the_run_did_not_forecast_is_a_404_with_guidance(
        self, client
    ) -> None:
        _seed()
        response = client.post("/api/scenarios", json={"scope_level": "series"})
        assert response.status_code == 404
        assert "series-level rows" in response.json()["error"]["message"]

    def test_the_caveats_state_that_stock_is_held_at_zero(self, client) -> None:
        _seed()
        caveats = " ".join(
            client.post("/api/scenarios", json={"scope_level": "branch"}).json()[
                "caveats"
            ]
        )
        assert "read-only" in caveats
        assert "zero on both sides" in caveats
        assert "does not re-fit any model" in caveats


class TestExports:
    def test_the_available_kinds_are_listed(self, client) -> None:
        body = client.get("/api/exports").json()
        kinds = {item["kind"] for item in body["kinds"]}
        assert kinds == {"leaderboard", "forecasts", "recommendations", "model_runs"}
        assert "never zero" in body["note"]

    def test_an_unknown_kind_is_refused_with_the_valid_set(self, client) -> None:
        response = client.get("/api/exports/telemetry")
        assert response.status_code == 422
        assert "leaderboard" in response.text

    def test_the_leaderboard_export_includes_every_model(self, client) -> None:
        _seed()
        response = client.get(
            "/api/exports/leaderboard",
            params={"scope_level": "branch", "scope_key": "JAIPUR"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        lines = response.text.splitlines()
        assert lines[0].startswith("# AIS leaderboard export")
        assert "training_run=" in lines[0]
        assert "unavailable_reason" in lines[1]

    def test_the_forecast_export_keeps_the_rows_that_have_no_forecast(
        self, client
    ) -> None:
        """An export that dropped them would be a different dataset from the
        one the page showed."""
        _seed()
        text = client.get(
            "/api/exports/forecasts", params={"scope_level": "branch"}
        ).text
        assert "MANDI" in text
        assert "not eligible" in text

    def test_an_undefined_metric_is_an_empty_cell_not_a_zero(self, client) -> None:
        _seed()
        text = client.get(
            "/api/exports/forecasts", params={"scope_level": "branch"}
        ).text
        rows = [line for line in text.splitlines() if line.startswith("branch,MANDI")]
        assert rows
        # point_forecast, q80, q90, q95 are all empty for a refused row.
        assert ",,,," in rows[0]

    def test_the_provenance_header_names_the_run_and_the_caveat(self, client) -> None:
        _seed()
        header = client.get("/api/exports/recommendations").text.splitlines()[0]
        assert "forecast_run=" in header
        assert "CURRENT-SNAPSHOT ESTIMATES" in header

    def test_no_completed_forecast_run_is_a_404_with_guidance(self, client) -> None:
        response = client.get("/api/exports/forecasts")
        assert response.status_code == 404
        assert "POST /api/forecasts/runs" in response.json()["error"]["remediation"]


class TestSettings:
    def test_it_publishes_the_effective_configuration(self, client) -> None:
        body = client.get("/api/settings").json()
        assert body["official_model_count"] == 13
        assert body["registered_model_ids"] == list(CANONICAL_MODEL_IDS)
        assert body["service_levels"] == [80, 90, 95]
        assert body["random_seed"] == 42
        assert body["review_period_days"] == 30
        assert body["stock_snapshot_date"] == "2026-08-01"

    def test_it_exposes_the_dialect_but_not_the_connection_string(self, client) -> None:
        body = client.get("/api/settings").json()
        assert body["database_dialect"] == "sqlite"
        serialised = str(body)
        assert "ais_test.db" not in serialised
        assert ".venv" not in serialised
        assert "C:\\" not in serialised

    def test_it_carries_the_structural_control_expectations(self, client) -> None:
        controls = client.get("/api/settings").json()["expected_controls"]
        assert controls["sales_rows"] == 1_703_042
        assert controls["order_rows"] == 775_912
        assert controls["sales_skus"] == 2_260
        assert controls["series"] == 63_210

    def test_there_is_no_write_endpoint(self, client) -> None:
        """Changing the seed or the history profile behind a stored run must be
        a deployment action, not a UI action."""
        assert client.post("/api/settings", json={"random_seed": 1}).status_code == 405
        assert client.put("/api/settings", json={"random_seed": 1}).status_code == 405
