"""Leaderboard, diagnostics and champion route contracts.

The rules being held to here are the ones the project's contract calls
load-bearing:

- all 13 registered models appear on every leaderboard, whatever their status,
  and `models_missing` reports any that do not,
- both rankings travel side by side and are never blended,
- a baseline appears, is flagged, and can never be champion,
- an override needs a real reason, cannot name a baseline or an unregistered
  model, and cannot name a model that did not complete in that scope,
- rollback writes a new row and leaves exactly one active selection,
- diagnostics for a model that did not run return its reason, not a curve.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.session import session_scope
from app.ml.registry.canonical_models import (
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
    MODEL_DISPLAY_NAMES,
)
from app.models.champions import ChampionSelection
from app.models.datasets import Dataset, DatasetVersion, IngestionStatus
from app.models.mappings import MappingVersion, PreprocessingRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, TrainingRun

#: A plausible metric per model, low enough that the champion is predictable.
_WAPE = {
    "var_exog": 4.578,
    "sarimax_exog": 6.192,
    "var": 9.603,
    "xgboost_exog": 10.603,
    "xgboost": 11.156,
    "sarimax": 13.157,
}
#: Measured on the real panel: the four `exp_*` variants and both Auto ARIMA
#: variants are ineligible at 22 training months.
_INELIGIBLE = (
    "auto_arima",
    "auto_arima_exog",
    "exp_additive",
    "exp_additive_damped",
    "exp_multiplicative",
    "exp_multiplicative_damped",
)


def _seed_run(
    *,
    scope_level: str = "national",
    scope_key: str = "NATIONAL",
    baseline_wape: float = 9.939,
    with_points: bool = True,
    omit: tuple[str, ...] = (),
) -> str:
    """One run whose national scope mirrors the real measured outcome."""
    with session_scope() as db:
        dataset = Dataset(name="Leaderboard fixture", source_label="source")
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
            training_cut_period="2025-09",
            period_count=28,
            series_count=68_675,
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
            origins_json={"primary_validation": {"shares": {"order": 100.0}}},
        )
        db.add(run)
        db.flush()
        run_id = run.id

        origins = (
            [
                {
                    "origin_name": "primary",
                    "fold_index": 0,
                    "train_end_period": "2025-09",
                    "train_rows": 18,
                    "status": "completed",
                    "periods": ["2025-10", "2025-11", "2025-12"],
                    "horizons": [1, 2, 3],
                    "actuals": [100.0, 120.0, 90.0],
                    "predictions": [110.0, 115.0, 99.0],
                    "metrics": {"wape": 6.0},
                    "legacy_metrics": {"mape": 8.0},
                    "fit_seconds": 0.4,
                    "predict_seconds": 0.01,
                    "negative_predictions": 0,
                }
            ]
            if with_points
            else [
                {
                    "origin_name": "primary",
                    "fold_index": 0,
                    "train_end_period": "2025-09",
                    "train_rows": 18,
                    "status": "completed",
                    "periods": ["2025-10"],
                    "horizons": [1],
                    "actuals": [],
                    "predictions": [],
                }
            ]
        )

        for model_id in CANONICAL_MODEL_IDS:
            if model_id in omit:
                continue
            if model_id in _INELIGIBLE:
                db.add(
                    ModelRun(
                        training_run_id=run_id,
                        tier="aggregate",
                        scope_level=scope_level,
                        scope_key=scope_key,
                        model_id=model_id,
                        display_name=MODEL_DISPLAY_NAMES[model_id],
                        status="ineligible",
                        evaluation_mode="rolling_origin",
                        failure_reason=(
                            f"{MODEL_DISPLAY_NAMES[model_id]} needs at least 24 "
                            "training observations; this window has 22."
                        ),
                        eligibility_json={"required_history": 24, "available": 22},
                        origins_total=2,
                        origins_json=[],
                    )
                )
                continue
            if model_id == "lstm":
                db.add(
                    ModelRun(
                        training_run_id=run_id,
                        tier="aggregate",
                        scope_level=scope_level,
                        scope_key=scope_key,
                        model_id=model_id,
                        display_name=MODEL_DISPLAY_NAMES[model_id],
                        status="completed",
                        evaluation_mode="holdout_fast",
                        wape=14.661,
                        # The one holdout_fast row needs the ranking metric as
                        # well, or it drops out of the ranking and the
                        # mixed-mode note this test is about never fires.
                        mape=16.661,
                        accuracy=83.339,
                        mae=25565.8,
                        bias=3.0,
                        bias_abs=3.0,
                        validation_points=6,
                        total_test_points=6,
                        duplicate_test_points=0,
                        origins_completed=1,
                        origins_total=1,
                        origins_json=origins,
                    )
                )
                continue
            wape = _WAPE[model_id]
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    tier="aggregate",
                    scope_level=scope_level,
                    scope_key=scope_key,
                    model_id=model_id,
                    display_name=MODEL_DISPLAY_NAMES[model_id],
                    status="completed",
                    evaluation_mode="rolling_origin",
                    wape=wape,
                    mae=wape * 1650,
                    bias=wape / 4,
                    bias_abs=wape / 4,
                    mape=wape + 2,
                    accuracy=max(0.0, 100.0 - (wape + 2)),
                    smape=wape + 1,
                    mase=wape / 10,
                    legacy_mape=wape + 2,
                    legacy_valid=True,
                    validation_points=10,
                    total_test_points=12,
                    duplicate_test_points=2,
                    origins_completed=2,
                    origins_total=2,
                    fit_seconds=1.2,
                    predict_seconds=0.02,
                    parameters_json={"order": [1, 0, 0]},
                    features_json=["lag_1", "month"],
                    origins_json=origins,
                )
            )

        for baseline in BASELINE_METHOD_IDS:
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    tier="aggregate",
                    scope_level=scope_level,
                    scope_key=scope_key,
                    model_id=baseline,
                    display_name=baseline,
                    is_baseline=True,
                    status="completed",
                    evaluation_mode="rolling_origin",
                    wape=baseline_wape if baseline == "ma6" else baseline_wape + 1.9,
                    # Baselines need the ranking metric too. They are compared
                    # against the champion on whichever metric ranks, and the
                    # fixture gives models `mape = wape + 2`, so a baseline
                    # without one would drop out of the comparison entirely
                    # and "beaten by a baseline" could never be true.
                    mape=(baseline_wape if baseline == "ma6" else baseline_wape + 1.9) + 2,
                    mae=(baseline_wape if baseline == "ma6" else baseline_wape + 1.9)
                    * 1650,
                    bias=1.0,
                    bias_abs=1.0,
                    validation_points=10,
                    total_test_points=12,
                    duplicate_test_points=2,
                    origins_completed=2,
                    origins_total=2,
                    origins_json=origins,
                )
            )
        return run_id


class TestLeaderboard:
    def test_all_thirteen_registered_models_appear(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        registered = [row for row in body["rows"] if not row["is_baseline"]]
        assert sorted(row["model_id"] for row in registered) == sorted(
            CANONICAL_MODEL_IDS
        )
        assert body["models_missing"] == []

    def test_a_model_absent_from_the_run_is_reported(self, client) -> None:
        _seed_run(omit=("lstm",))
        body = client.get("/api/models/leaderboard").json()
        assert body["models_missing"] == ["lstm"]

    def test_the_champion_is_the_lowest_wape_registered_model(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        assert body["champion_model_id"] == "var_exog"
        assert body["challenger_model_id"] == "sarimax_exog"
        champion = next(row for row in body["rows"] if row["is_champion"])
        assert champion["model_id"] == "var_exog"
        assert champion["rank"] == 1

    def test_ineligible_models_are_present_with_their_requirement(self, client) -> None:
        _seed_run()
        rows = {row["model_id"]: row for row in client.get("/api/models/leaderboard").json()["rows"]}
        for model_id in _INELIGIBLE:
            row = rows[model_id]
            assert row["status"] == "ineligible"
            assert row["rank"] is None
            assert row["ranked"] is False
            assert "24" in row["failure_reason"]
            assert row["exclusion_reason"]
            assert row["wape"] is None

    def test_baselines_are_flagged_unranked_and_never_champion(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        baselines = [row for row in body["rows"] if row["is_baseline"]]
        assert {row["model_id"] for row in baselines} == set(BASELINE_METHOD_IDS)
        for row in baselines:
            assert row["is_champion"] is False
            assert row["rank"] is None
            assert row["exclusion"] == "is_baseline"
        assert body["baselines_present"] == sorted(BASELINE_METHOD_IDS)

    def test_a_champion_beaten_by_a_baseline_is_stated_not_implied(self, client) -> None:
        # A baseline better than every registered model.
        _seed_run(baseline_wape=1.0)
        body = client.get("/api/models/leaderboard").json()
        assert body["beaten_by_baseline"] is True
        assert body["best_baseline_model_id"] == "ma6"
        assert body["skill_vs_best_baseline"]["champion_better"] is False
        assert any("beats the champion" in note for note in body["notes"])

    def test_beating_the_baselines_reports_a_positive_skill_score(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        assert body["beaten_by_baseline"] is False
        skill = body["skill_vs_best_baseline"]
        assert skill["champion_better"] is True
        assert skill["improvement_pct"] > 0

    def test_both_rankings_are_returned_side_by_side(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        assert body["legacy_champion_model_id"] == "var_exog"
        champion = next(row for row in body["rows"] if row["is_champion"])
        assert champion["rank"] == 1
        assert champion["legacy_rank"] == 1
        assert champion["mape"] is not None
        assert champion["wape"] is not None

    def test_a_fast_holdout_row_carries_its_mode_and_point_count(self, client) -> None:
        _seed_run()
        rows = {row["model_id"]: row for row in client.get("/api/models/leaderboard").json()["rows"]}
        lstm = rows["lstm"]
        assert lstm["evaluation_mode"] == "holdout_fast"
        assert lstm["validation_points"] == 6
        assert rows["xgboost"]["validation_points"] == 10
        body = client.get("/api/models/leaderboard").json()
        assert any("D-037" in note for note in body["notes"])

    def test_the_window_composition_travels_with_the_metrics(self, client) -> None:
        """D-040's sales-proxy caveat must not be left behind on another page."""
        _seed_run()
        body = client.get("/api/models/leaderboard").json()
        assert body["origins"]["primary_validation"]["shares"]["order"] == 100.0

    def test_the_full_metric_set_is_exposed(self, client) -> None:
        _seed_run()
        champion = next(
            row
            for row in client.get("/api/models/leaderboard").json()["rows"]
            if row["is_champion"]
        )
        for key in (
            "wape",
            "mape",
            "accuracy",
            "mae",
            "rmse",
            "smape",
            "mase",
            "bias",
            "validation_points",
            "origins_completed",
        ):
            assert key in champion

    def test_an_unknown_scope_is_a_structured_404_with_guidance(self, client) -> None:
        _seed_run()
        response = client.get(
            "/api/models/leaderboard", params={"scope_key": "ATLANTIS"}
        )
        assert response.status_code == 404
        assert "evaluated no models" in response.json()["error"]["message"]
        assert "never reached" in response.json()["error"]["remediation"]

    def test_no_run_at_all_is_a_404_pointing_at_training(self, client) -> None:
        response = client.get("/api/models/leaderboard")
        assert response.status_code == 404
        assert "POST /api/training" in response.json()["error"]["remediation"]


class TestComparisonChart:
    def test_every_model_is_a_bar_including_the_ones_that_did_not_run(
        self, client
    ) -> None:
        _seed_run()
        points = client.get("/api/models/leaderboard/comparison").json()
        assert len(points) == len(CANONICAL_MODEL_IDS) + len(BASELINE_METHOD_IDS)
        gaps = [point for point in points if point["wape"] is None]
        assert {point["model_id"] for point in gaps} == set(_INELIGIBLE)
        for point in gaps:
            assert point["exclusion_reason"]

    def test_wape_pct_is_not_double_scaled(self, client) -> None:
        """WAPE is already a percentage at source; 4.578 must not become 458."""
        _seed_run()
        points = {
            point["model_id"]: point
            for point in client.get("/api/models/leaderboard/comparison").json()
        }
        assert points["var_exog"]["wape_pct"] == pytest.approx(4.578)


class TestScopes:
    def test_the_scopes_a_run_covers_are_listed(self, client) -> None:
        run_id = _seed_run()
        with session_scope() as db:
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    tier="aggregate",
                    scope_level="branch",
                    scope_key="JAIPUR",
                    model_id="xgboost",
                    display_name="XGBoost",
                    status="completed",
                    wape=8.0,
                    validation_points=10,
                )
            )
        body = client.get("/api/models/leaderboard/scopes").json()
        pairs = {(item["scope_level"], item["scope_key"]) for item in body["items"]}
        assert ("national", "NATIONAL") in pairs
        assert ("branch", "JAIPUR") in pairs

    def test_scopes_can_be_filtered_by_level(self, client) -> None:
        _seed_run()
        body = client.get(
            "/api/models/leaderboard/scopes", params={"scope_level": "branch"}
        ).json()
        assert body["total"] == 0


class TestDiagnostics:
    def test_folds_points_and_horizon_performance_are_served(self, client) -> None:
        _seed_run()
        body = client.get("/api/models/var_exog/diagnostics").json()
        assert body["diagnostics_available"] is True
        assert len(body["folds"]) == 1
        assert len(body["points"]) == 3
        assert body["folds"][0]["train_end_period"] == "2025-09"
        horizons = {row["horizon"] for row in body["horizon_performance"]}
        assert horizons == {1, 2, 3}

    def test_residuals_are_predicted_minus_actual(self, client) -> None:
        _seed_run()
        point = client.get("/api/models/var_exog/diagnostics").json()["points"][0]
        assert point["actual"] == 100.0
        assert point["predicted"] == 110.0
        assert point["residual"] == 10.0

    def test_horizon_performance_reports_points_and_bias(self, client) -> None:
        _seed_run()
        rows = {
            row["horizon"]: row
            for row in client.get("/api/models/var_exog/diagnostics").json()[
                "horizon_performance"
            ]
        }
        assert rows[1]["points"] == 1
        assert rows[1]["mae"] == pytest.approx(10.0)
        assert rows[1]["bias"] == pytest.approx(10.0)
        assert rows[2]["mae"] == pytest.approx(5.0)
        # A percentage, like every other WAPE in the payload: 10/100 -> 10.0,
        # not 0.1.
        assert rows[1]["wape"] == pytest.approx(10.0)

    def test_a_model_that_did_not_run_returns_its_reason_not_a_curve(
        self, client
    ) -> None:
        _seed_run()
        body = client.get("/api/models/auto_arima/diagnostics").json()
        assert body["status"] == "ineligible"
        assert body["diagnostics_available"] is False
        assert body["points"] == []
        assert "24" in body["unavailable_reason"]
        assert body["eligibility"]["required_history"] == 24

    def test_a_completed_model_without_stored_points_says_so_honestly(
        self, client
    ) -> None:
        """The gap is in the record, not in the model - the message must not
        blame the model for producing no predictions."""
        _seed_run(with_points=False)
        body = client.get("/api/models/var_exog/diagnostics").json()
        assert body["status"] == "completed"
        assert body["diagnostics_available"] is False
        assert "did not persist" in body["unavailable_reason"]
        assert body["metrics"]["wape"] is not None

    def test_an_unknown_model_in_this_scope_is_a_404(self, client) -> None:
        _seed_run()
        response = client.get("/api/models/prophet/diagnostics")
        assert response.status_code == 404


class TestChampionSelection:
    def test_selection_writes_one_active_row_per_scope(self, client) -> None:
        run_id = _seed_run()
        body = client.post(
            "/api/models/champions/select",
            json={"training_run_id": run_id, "scope_kinds": ["overall"]},
        ).json()
        assert body["selected_count"] == 1
        selection = body["selected"][0]
        assert selection["champion_model_id"] == "var_exog"
        assert selection["selection_source"] == "automatic"
        assert selection["is_active"] is True
        assert selection["challenger_model_id"] == "sarimax_exog"

    def test_a_scope_with_no_rankable_model_is_skipped_with_a_reason(
        self, client
    ) -> None:
        run_id = _seed_run()
        with session_scope() as db:
            # A branch where every model was ineligible.
            for model_id in CANONICAL_MODEL_IDS:
                db.add(
                    ModelRun(
                        training_run_id=run_id,
                        tier="aggregate",
                        scope_level="branch",
                        scope_key="MANDI",
                        model_id=model_id,
                        display_name=MODEL_DISPLAY_NAMES[model_id],
                        status="ineligible",
                        failure_reason="Not enough history.",
                    )
                )
        body = client.post(
            "/api/models/champions/select",
            json={"training_run_id": run_id, "scope_kinds": ["branch"]},
        ).json()
        assert body["selected_count"] == 0
        assert body["skipped_count"] == 1
        skipped = body["skipped"][0]
        assert skipped["scope_key"] == "MANDI"
        assert "no champion was invented" in skipped["reason"].lower()

    def test_the_baseline_verdict_is_recorded_on_the_selection(self, client) -> None:
        run_id = _seed_run(baseline_wape=1.0)
        selection = client.post(
            "/api/models/champions/select",
            json={"training_run_id": run_id, "scope_kinds": ["overall"]},
        ).json()["selected"][0]
        assert selection["beaten_by_baseline"] is True
        assert selection["best_baseline_model_id"] == "ma6"

    def test_an_unknown_scope_kind_is_rejected_with_the_valid_set(self, client) -> None:
        run_id = _seed_run()
        response = client.post(
            "/api/models/champions/select",
            json={"training_run_id": run_id, "scope_kinds": ["galaxy"]},
        )
        assert response.status_code == 422
        assert "overall" in response.text

    def test_current_champion_is_404_before_any_selection(self, client) -> None:
        _seed_run()
        response = client.get("/api/models/champions/current")
        assert response.status_code == 404
        assert "champions/select" in response.json()["error"]["remediation"]


class TestOverrideAndRollback:
    def _selected(self, client) -> str:
        run_id = _seed_run()
        client.post(
            "/api/models/champions/select",
            json={"training_run_id": run_id, "scope_kinds": ["overall"]},
        )
        return run_id

    def test_an_override_records_who_why_and_what_it_replaced(self, client) -> None:
        self._selected(client)
        response = client.post(
            "/api/models/champion/override",
            json={
                "model_id": "xgboost",
                "reason": "Planner prefers the pooled-capable model for rollout.",
                "actor": "vijju",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["champion_model_id"] == "xgboost"
        assert body["selection_source"] == "manual_override"
        assert body["actor"] == "vijju"
        assert body["supersedes_id"]
        assert body["is_active"] is True

    def test_exactly_one_selection_stays_active_per_scope(self, client) -> None:
        self._selected(client)
        client.post(
            "/api/models/champion/override",
            json={
                "model_id": "xgboost",
                "reason": "A perfectly adequate written reason.",
            },
        )
        with session_scope() as db:
            active = (
                db.query(ChampionSelection)
                .filter(
                    ChampionSelection.scope_kind == "overall",
                    ChampionSelection.is_active.is_(True),
                )
                .count()
            )
        assert active == 1

    def test_a_short_reason_is_refused(self, client) -> None:
        self._selected(client)
        response = client.post(
            "/api/models/champion/override",
            json={"model_id": "xgboost", "reason": "why"},
        )
        assert response.status_code == 422

    def test_a_baseline_cannot_be_made_champion(self, client) -> None:
        self._selected(client)
        response = client.post(
            "/api/models/champion/override",
            json={
                "model_id": "ma6",
                "reason": "The moving average is genuinely better here.",
            },
        )
        assert response.status_code == 409
        assert "non-registry baseline" in response.json()["error"]["message"]

    def test_an_unregistered_model_cannot_be_made_champion(self, client) -> None:
        self._selected(client)
        response = client.post(
            "/api/models/champion/override",
            json={
                "model_id": "prophet",
                "reason": "Prophet looked good in the analysis document.",
            },
        )
        assert response.status_code == 422
        assert "not one of the 13" in response.json()["error"]["message"]

    def test_a_model_that_did_not_complete_cannot_be_made_champion(
        self, client
    ) -> None:
        """Overriding to an ineligible model would claim an accuracy that was
        never measured."""
        self._selected(client)
        response = client.post(
            "/api/models/champion/override",
            json={
                "model_id": "auto_arima",
                "reason": "It is my preferred statistical model overall.",
            },
        )
        assert response.status_code == 409
        assert "ineligible" in response.json()["error"]["message"]

    def test_the_history_holds_every_decision_newest_first(self, client) -> None:
        self._selected(client)
        client.post(
            "/api/models/champion/override",
            json={
                "model_id": "xgboost",
                "reason": "Switching for rollout consistency reasons.",
            },
        )
        body = client.get("/api/models/champions/history").json()
        assert body["total"] == 2
        assert [entry["selection_source"] for entry in body["entries"]] == [
            "manual_override",
            "automatic",
        ]
        assert [entry["is_active"] for entry in body["entries"]] == [True, False]

    def test_rollback_restores_the_previous_choice_as_a_new_row(self, client) -> None:
        self._selected(client)
        client.post(
            "/api/models/champion/override",
            json={
                "model_id": "xgboost",
                "reason": "Switching for rollout consistency reasons.",
            },
        )
        response = client.post("/api/models/champion/rollback", json={})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["champion_model_id"] == "var_exog"
        assert body["selection_source"] == "rollback"
        assert body["restored_from_id"]
        assert body["reason"]
        history = client.get("/api/models/champions/history").json()
        assert history["total"] == 3

    def test_rollback_with_nothing_to_restore_is_refused(self, client) -> None:
        self._selected(client)
        response = client.post("/api/models/champion/rollback", json={})
        assert response.status_code == 409
        assert "nothing to roll back" in response.json()["error"]["message"]

    def test_rollback_on_an_unknown_scope_is_a_404(self, client) -> None:
        self._selected(client)
        response = client.post(
            "/api/models/champion/rollback",
            json={"scope_kind": "branch", "scope_key": "ATLANTIS"},
        )
        assert response.status_code == 404


class TestPiiExclusion:
    def test_no_leaderboard_or_champion_field_can_carry_pii(self) -> None:
        from app.domain.ais.source_spec import ALL_PII_COLUMNS
        from app.schemas.champions import (
            ChampionSelectionOut,
            DiagnosticsResponse,
            LeaderboardRow,
        )

        forbidden = {name.lower().replace(" ", "_") for name in ALL_PII_COLUMNS}
        fields = (
            set(LeaderboardRow.model_fields)
            | set(ChampionSelectionOut.model_fields)
            | set(DiagnosticsResponse.model_fields)
        )
        assert not (fields & forbidden)
