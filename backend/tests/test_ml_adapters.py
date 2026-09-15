"""The 13 adapters: interface, eligibility, failure isolation, persistence.

Fits run on small synthetic series so the suite stays fast. The models were
also exercised against the real AIS panel end to end (docs/STATUS.md); these
tests pin the contract.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.domain.ais.exog_features import (
    CALENDAR_EXOG_COLUMNS,
    attach_calendar_exog,
    prepare_local_series_frame,
    resolve_exog_columns,
)
from app.ml.adapters.base import (
    Eligibility,
    EligibilityCode,
    ForecastModelAdapter,
    ModelContext,
    ModelNotFittedError,
    clean_predictions,
)
from app.ml.evaluation.seasonality import (
    resolve_seasonal_period,
    smallest_fold_train_size,
)
from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS
from app.ml.registry.model_registry import (
    MODEL_REGISTRY,
    assert_registry_bound,
    create_adapter,
    create_all_adapters,
    ordered_adapter_classes,
)

pytestmark = pytest.mark.filterwarnings("ignore")


def _series(values: list[float], *, start_index: int = 24_291) -> pd.DataFrame:
    """A per-series frame shaped like the real panel."""
    frame = pd.DataFrame(
        {
            "series_id": "AGRA|FG.X",
            "period_index": range(start_index, start_index + len(values)),
            "target": [float(v) for v in values],
            "despatched_qty": [max(0.0, float(v) - (index % 3)) for index, v in enumerate(values)],
            "is_censored": [False] * len(values),
            "target_source": ["order"] * len(values),
        }
    )
    return attach_calendar_exog(frame)


def _dense(months: int = 36) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    base = 40 + 12 * np.sin(np.arange(months) * 2 * np.pi / 12)
    return _series(list(np.round(base + rng.normal(0, 3, months), 1)))


def _direct_frame(months: int = 60) -> pd.DataFrame:
    """A direct multi-horizon frame, as Phase 4 produces."""
    rng = np.random.default_rng(11)
    rows = []
    for series in ("A|X", "B|Y"):
        for origin in range(months):
            for horizon in (1, 2, 3):
                rows.append(
                    {
                        "series_id": series,
                        "period_index": 24_291 + origin,
                        "target_period": 24_291 + origin + horizon,
                        "horizon": horizon,
                        "lag_1": float(rng.integers(0, 60)),
                        "lag_2": float(rng.integers(0, 60)),
                        "rolling_mean_3": float(rng.integers(0, 60)),
                        "calendar_month": (origin + horizon) % 12 + 1,
                        "region": "NORTH-1" if series == "A|X" else "WEST",
                        "y": float(rng.integers(0, 60)),
                    }
                )
    return pd.DataFrame(rows)


def _context(**overrides) -> ModelContext:
    base = {"seasonal_period": 12, "exog_columns": CALENDAR_EXOG_COLUMNS}
    base.update(overrides)
    return ModelContext(**base)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class TestRegistryBinding:
    def test_exactly_thirteen_adapters_are_bound(self) -> None:
        assert len(MODEL_REGISTRY) == 13
        assert tuple(MODEL_REGISTRY) == CANONICAL_MODEL_IDS

    def test_the_import_time_assertion_passes(self) -> None:
        assert_registry_bound()

    def test_every_adapter_subclasses_the_common_contract(self) -> None:
        for adapter in ordered_adapter_classes():
            assert issubclass(adapter, ForecastModelAdapter)

    def test_every_adapter_declares_the_full_interface(self) -> None:
        required = (
            "model_id", "display_name", "dependency_module", "requires_exogenous",
            "supports_pooled_training", "uses_fast_holdout", "family",
            "min_required_history", "validate_eligibility", "fit", "predict",
            "parameter_metadata", "feature_metadata", "save", "load",
        )
        for adapter in create_all_adapters():
            for member in required:
                assert hasattr(adapter, member), f"{adapter.model_id} lacks {member}"

    def test_diagnostics_carry_timing_and_failure_slots(self) -> None:
        for adapter in create_all_adapters():
            diagnostics = adapter.diagnostics.as_dict()
            for key in (
                "training_duration_ms", "inference_duration_ms", "failure_reason",
                "parameters", "features",
            ):
                assert key in diagnostics

    def test_create_all_returns_display_order(self) -> None:
        assert [a.model_id for a in create_all_adapters()] == list(CANONICAL_MODEL_IDS)

    def test_an_unknown_id_names_the_valid_ones(self) -> None:
        with pytest.raises(KeyError, match="Unknown model_id"):
            create_adapter("prophet")

    def test_lstm_has_no_exogenous_sibling(self) -> None:
        """Inventing one would make it a fourteenth model."""
        assert "lstm_exog" not in MODEL_REGISTRY
        assert create_adapter("lstm").requires_exogenous is False


# --------------------------------------------------------------------------
# Eligibility: a verdict, never an exception
# --------------------------------------------------------------------------

class TestEligibilityIsAVerdict:
    def test_it_never_raises_on_an_empty_frame(self) -> None:
        empty = _series([]).iloc[0:0]
        for adapter in create_all_adapters(_context()):
            verdict = adapter.validate_eligibility(empty, _context())
            assert isinstance(verdict, Eligibility)
            assert verdict.eligible is False

    def test_a_frame_with_no_label_is_reported_not_raised(self) -> None:
        frame = pd.DataFrame({"period_index": [1, 2, 3]})
        verdict = create_adapter("sarimax").validate_eligibility(frame, _context())
        assert verdict.code is EligibilityCode.NO_VALID_TARGET
        assert "label columns" in verdict.reason

    def test_an_all_missing_target_is_reported(self) -> None:
        frame = _series([1.0] * 30)
        frame["target"] = np.nan
        verdict = create_adapter("sarimax").validate_eligibility(frame, _context())
        assert verdict.code is EligibilityCode.NO_VALID_TARGET

    def test_short_history_states_the_requirement_and_the_shortfall(self) -> None:
        verdict = create_adapter("auto_arima").validate_eligibility(
            _series([1.0] * 10), _context()
        )
        assert verdict.code is EligibilityCode.INSUFFICIENT_HISTORY
        assert verdict.required_history == 24
        assert verdict.observed_history == 10
        assert "more month" in verdict.remediation

    def test_every_ineligible_verdict_carries_a_remediation(self) -> None:
        for adapter in create_all_adapters(_context()):
            verdict = adapter.validate_eligibility(_series([1.0, 2.0]), _context())
            if not verdict.eligible:
                assert verdict.remediation, f"{adapter.model_id} gave no remediation"

    def test_the_reference_profile_leaves_six_models_ineligible(self) -> None:
        """The measured AIS reality: 22 training months against a 24-month
        requirement (docs/DECISIONS.md D-001)."""
        frame = _dense(22)
        context = _context(seasonal_period=None, min_history_profile="reference")
        ineligible = [
            adapter.model_id
            for adapter in create_all_adapters(context)
            if not adapter.validate_eligibility(frame, context).eligible
        ]
        assert set(ineligible) == {
            "auto_arima", "auto_arima_exog", "exp_additive", "exp_additive_damped",
            "exp_multiplicative", "exp_multiplicative_damped",
        }

    def test_the_relaxed_profile_admits_every_model(self) -> None:
        """With a shorter resolved period, all 13 become evaluable - which is
        what D-001 promises the opt-in delivers."""
        frame = _dense(22)
        resolution = resolve_seasonal_period(
            frame["target"], profile="monthly_relaxed"
        )
        assert resolution.period is not None and resolution.period < 12
        context = _context(
            seasonal_period=resolution.period, min_history_profile="monthly_relaxed"
        )
        ineligible = [
            adapter.model_id
            for adapter in create_all_adapters(context)
            if not adapter.validate_eligibility(frame, context).eligible
        ]
        assert ineligible == []


class TestMultiplicativePositivity:
    @pytest.mark.parametrize(
        "model_id", ["exp_multiplicative", "exp_multiplicative_damped"]
    )
    def test_a_zero_month_makes_it_ineligible(self, model_id: str) -> None:
        frame = _dense(36)
        frame.loc[5, "target"] = 0.0
        verdict = create_adapter(model_id).validate_eligibility(frame, _context())
        assert verdict.eligible is False
        assert verdict.code is EligibilityCode.NON_POSITIVE_TARGET

    @pytest.mark.parametrize(
        "model_id", ["exp_multiplicative", "exp_multiplicative_damped"]
    )
    def test_no_positive_floor_is_introduced(self, model_id: str) -> None:
        """62% of AIS series are intermittent. Shifting the target to force
        eligibility would change what is being forecast."""
        frame = _dense(36)
        frame.loc[5, "target"] = 0.0
        verdict = create_adapter(model_id).validate_eligibility(frame, _context())
        assert "no positive floor" in verdict.remediation.lower()
        # The frame itself is untouched.
        assert frame.loc[5, "target"] == 0.0

    @pytest.mark.parametrize("model_id", ["exp_additive", "exp_additive_damped"])
    def test_additive_variants_tolerate_zeros(self, model_id: str) -> None:
        frame = _dense(36)
        frame.loc[5, "target"] = 0.0
        assert create_adapter(model_id).validate_eligibility(frame, _context()).eligible


class TestSeasonalCycleGate:
    def test_an_unresolvable_period_makes_the_es_variants_ineligible(self) -> None:
        context = _context(seasonal_period=None)
        for model_id in (
            "exp_additive", "exp_additive_damped",
            "exp_multiplicative", "exp_multiplicative_damped",
        ):
            verdict = create_adapter(model_id).validate_eligibility(_dense(36), context)
            assert verdict.eligible is False
            assert verdict.code is EligibilityCode.INSUFFICIENT_SEASONAL_CYCLES

    def test_two_full_cycles_are_required(self) -> None:
        verdict = create_adapter("exp_additive").validate_eligibility(
            _dense(30), _context(seasonal_period=12, min_history_profile="monthly_relaxed")
        )
        assert verdict.eligible is True
        short = create_adapter("exp_additive").validate_eligibility(
            _dense(20), _context(seasonal_period=12, min_history_profile="monthly_relaxed")
        )
        assert short.eligible is False
        assert short.required_history == 24


class TestExogenousGate:
    @pytest.mark.parametrize(
        "model_id", ["sarimax_exog", "auto_arima_exog", "var_exog"]
    )
    def test_no_exogenous_columns_is_ineligible(self, model_id: str) -> None:
        verdict = create_adapter(model_id).validate_eligibility(
            _dense(36), _context(exog_columns=())
        )
        assert verdict.eligible is False
        assert verdict.code in {
            EligibilityCode.NO_VARYING_EXOGENOUS,
            EligibilityCode.INSUFFICIENT_ENDOGENOUS,
        }

    def test_a_constant_exogenous_column_is_ineligible(self) -> None:
        frame = _dense(36)
        frame["flat_driver"] = 1.0
        verdict = create_adapter("sarimax_exog").validate_eligibility(
            frame, _context(exog_columns=("flat_driver",))
        )
        assert verdict.eligible is False
        assert "constant" in verdict.reason.lower()

    def test_xgboost_exog_in_direct_mode_needs_no_separate_gate(self) -> None:
        """In direct mode the drivers are already features of the frame."""
        verdict = create_adapter("xgboost_exog").validate_eligibility(
            _direct_frame(), _context(exog_columns=())
        )
        assert verdict.eligible is True


class TestVarEndogenousGate:
    def test_a_constant_pair_makes_var_ineligible_not_failed(self) -> None:
        frame = _dense(36)
        frame["despatched_qty"] = 5.0
        verdict = create_adapter("var").validate_eligibility(frame, _context())
        assert verdict.eligible is False
        assert verdict.code is EligibilityCode.INSUFFICIENT_ENDOGENOUS
        assert "not failed" in verdict.remediation.lower()

    def test_a_varying_pair_is_eligible(self) -> None:
        assert create_adapter("var").validate_eligibility(_dense(36), _context()).eligible


# --------------------------------------------------------------------------
# Fit, predict, metadata
# --------------------------------------------------------------------------

class TestFitAndPredict:
    LOCAL_MODELS = ("sarimax", "sarimax_exog", "var", "var_exog")

    @pytest.mark.parametrize("model_id", LOCAL_MODELS)
    def test_it_fits_and_predicts_the_requested_length(self, model_id: str) -> None:
        frame = _dense(36)
        adapter = create_adapter(model_id, _context())
        assert adapter.validate_eligibility(frame, _context()).eligible
        adapter.fit(frame.iloc[:30], _context())
        predictions = adapter.predict(frame.iloc[30:], _context())
        assert len(predictions) == 6

    @pytest.mark.parametrize("model_id", LOCAL_MODELS)
    def test_timings_are_recorded(self, model_id: str) -> None:
        frame = _dense(36)
        adapter = create_adapter(model_id, _context())
        adapter.fit(frame.iloc[:30], _context())
        adapter.predict(frame.iloc[30:], _context())
        assert adapter.diagnostics.training_duration_ms > 0
        assert adapter.diagnostics.inference_duration_ms is not None
        assert adapter.diagnostics.training_rows == 30

    @pytest.mark.parametrize("model_id", LOCAL_MODELS)
    def test_parameter_metadata_names_its_source(self, model_id: str) -> None:
        frame = _dense(36)
        adapter = create_adapter(model_id, _context())
        adapter.fit(frame.iloc[:30], _context())
        assert "ported_from" in adapter.parameter_metadata()

    def test_predicting_before_fitting_raises(self) -> None:
        adapter = create_adapter("sarimax", _context())
        with pytest.raises(ModelNotFittedError):
            adapter.predict(_dense(6), _context())

    def test_a_failed_fit_records_its_reason(self) -> None:
        frame = _dense(36)
        frame["despatched_qty"] = 5.0  # collapses VAR's endogenous set
        adapter = create_adapter("var", _context())
        with pytest.raises(ValueError):
            adapter.fit(frame, _context())
        assert adapter.diagnostics.failure_reason
        assert adapter.diagnostics.fitted is False

    def test_one_adapter_failing_leaves_the_others_usable(self) -> None:
        """Failure isolation, as both references guarantee."""
        frame = _dense(36)
        frame["despatched_qty"] = 5.0
        outcomes: dict[str, str] = {}
        for adapter in create_all_adapters(_context()):
            if adapter.model_id in {"var", "var_exog"}:
                try:
                    adapter.fit(frame, _context())
                    outcomes[adapter.model_id] = "completed"
                except Exception:
                    outcomes[adapter.model_id] = "failed"
            elif adapter.model_id == "sarimax":
                adapter.fit(frame.iloc[:30], _context())
                outcomes[adapter.model_id] = "completed"
        assert outcomes["var"] == "failed"
        assert outcomes["sarimax"] == "completed"


class TestSarimaxOrderGuard:
    def test_the_ar_order_drops_to_one_at_period_two(self) -> None:
        """statsmodels rejects a non-seasonal AR lag coinciding with a seasonal
        one, which happens at period 2. Sodexo's guard; Meriton has none."""
        adapter = create_adapter("sarimax", _context(seasonal_period=2))
        order, seasonal = adapter._resolve_orders(30, _context(seasonal_period=2))
        assert order == (1, 1, 1)
        assert seasonal == (1, 0, 1, 2)

    def test_the_ar_order_is_two_at_period_twelve(self) -> None:
        adapter = create_adapter("sarimax", _context())
        order, seasonal = adapter._resolve_orders(40, _context())
        assert order == (2, 1, 1)
        assert seasonal == (1, 0, 1, 12)

    def test_seasonal_terms_need_three_cycles(self) -> None:
        """Sodexo gates on period*3, not period*2."""
        adapter = create_adapter("sarimax", _context())
        _, seasonal = adapter._resolve_orders(30, _context())
        assert seasonal == (0, 0, 0, 0)
        _, active = adapter._resolve_orders(36, _context())
        assert active == (1, 0, 1, 12)

    def test_stationarity_enforcement_is_off(self) -> None:
        frame = _dense(40)
        adapter = create_adapter("sarimax", _context())
        adapter.fit(frame, _context())
        params = adapter.parameter_metadata()
        assert params["enforce_stationarity"] is False
        assert params["enforce_invertibility"] is False


class TestXGBoostModes:
    def test_a_direct_frame_selects_direct_mode(self) -> None:
        adapter = create_adapter("xgboost", _context(xgboost_training_profile="fast"))
        adapter.fit(_direct_frame(), _context(xgboost_training_profile="fast"))
        assert adapter.parameter_metadata()["forecast_mode"] == "direct"

    def test_direct_mode_answers_every_horizon_from_one_fit(self) -> None:
        frame = _direct_frame()
        context = _context(xgboost_training_profile="fast")
        adapter = create_adapter("xgboost", context)
        adapter.fit(frame, context)
        predictions = adapter.predict(frame.head(9), context)
        assert len(predictions) == 9

    def test_a_series_frame_selects_recursive_mode(self) -> None:
        context = _context(xgboost_training_profile="fast")
        adapter = create_adapter("xgboost", context)
        adapter.fit(_dense(36), context)
        assert adapter.parameter_metadata()["forecast_mode"] == "recursive"

    def test_recursion_does_not_consume_actuals_by_default(self) -> None:
        """Both references append the ACTUAL when the output frame has one
        (Meriton :1130, Sodexo :211), making a fold one-step-ahead. AIS feeds
        its own predictions instead (docs/DECISIONS.md D-031)."""
        frame = _dense(40)
        context = _context(xgboost_training_profile="fast")
        assert context.allow_actuals_in_recursion is False

        adapter = create_adapter("xgboost", context)
        adapter.fit(frame.iloc[:34], context)
        with_actuals = frame.iloc[34:].copy()
        without = with_actuals.copy()
        without["target"] = np.nan

        honest = adapter.predict(with_actuals, context)
        blinded = adapter.predict(without, context)
        # Identical, because the actuals were ignored either way.
        pd.testing.assert_series_equal(honest, blinded)

    def test_the_reference_recursion_is_available_for_parity(self) -> None:
        frame = _dense(40)
        reference = _context(
            xgboost_training_profile="fast", allow_actuals_in_recursion=True
        )
        adapter = create_adapter("xgboost", reference)
        adapter.fit(frame.iloc[:34], reference)
        with_actuals = frame.iloc[34:].copy()
        blinded = with_actuals.copy()
        blinded["target"] = np.nan
        # Now the actuals DO change the walk, which is the reference behaviour.
        assert not adapter.predict(with_actuals, reference).equals(
            adapter.predict(blinded, reference)
        )

    def test_the_feature_dtype_is_uniform(self) -> None:
        """Mixed dtypes change XGBoost's hist binning and move predictions."""
        context = _context(xgboost_training_profile="fast")
        adapter = create_adapter("xgboost", context)
        frame = _direct_frame()
        adapter.fit(frame, context)
        matrix, _ = adapter._direct_matrix(frame, fitting=False)
        assert matrix.dtypes.nunique() == 1
        assert str(matrix.dtypes.iloc[0]) == "float32"

    def test_an_unseen_category_becomes_minus_one(self) -> None:
        context = _context(xgboost_training_profile="fast")
        adapter = create_adapter("xgboost", context)
        frame = _direct_frame()
        adapter.fit(frame, context)
        unseen = frame.head(3).copy()
        unseen["region"] = "MARS"
        matrix, _ = adapter._direct_matrix(unseen, fitting=False)
        assert (matrix["region"] == -1).all()

    def test_the_thorough_profile_records_its_grid_choice(self) -> None:
        context = _context(xgboost_training_profile="thorough")
        adapter = create_adapter("xgboost", context)
        adapter.fit(_direct_frame(24), context)
        params = adapter.parameter_metadata()
        assert params["selection"] == "GridSearchCV(cv=2)"
        assert params["max_depth"] in {3, 5}

    def test_the_fast_profile_uses_the_fixed_parameters(self) -> None:
        context = _context(xgboost_training_profile="fast")
        adapter = create_adapter("xgboost", context)
        adapter.fit(_direct_frame(24), context)
        params = adapter.parameter_metadata()
        assert params["selection"] == "fixed"
        assert params["max_depth"] == 4


class TestVarBehaviour:
    def test_the_target_is_read_from_column_zero(self) -> None:
        """Meriton sums its endogenous columns, which is right when they are
        slices of one target. Here they are different quantities - ordered
        versus despatched - so summing would forecast their total."""
        frame = _dense(36)
        adapter = create_adapter("var", _context())
        adapter.fit(frame.iloc[:30], _context())
        assert adapter.parameter_metadata()["target_read_from_column"] == 0
        predictions = adapter.predict(frame.iloc[30:], _context())
        # Predictions stay in the target's range, not the sum of both series.
        assert predictions.max() < frame["target"].max() * 2

    def test_a_constant_column_is_dropped_with_its_offset_carried(self) -> None:
        frame = _dense(36)
        frame["mean_mrp"] = 100.0
        adapter = create_adapter("var", _context())
        adapter.fit(frame.iloc[:30], _context())
        params = adapter.parameter_metadata()
        assert "mean_mrp" not in params["endogenous_columns"]

    def test_the_paired_series_is_labelled_censored(self) -> None:
        frame = _dense(36)
        adapter = create_adapter("var", _context())
        adapter.fit(frame.iloc[:30], _context())
        note = adapter.parameter_metadata()["paired_series_note"]
        assert "censored" in note
        assert "not a second demand truth" in note


class TestExpSmoothingParity:
    @pytest.mark.parametrize(
        ("model_id", "seasonal", "damped"),
        [
            ("exp_additive", "add", False),
            ("exp_additive_damped", "add", True),
            ("exp_multiplicative", "mul", False),
            ("exp_multiplicative_damped", "mul", True),
        ],
    )
    def test_each_variant_configures_its_own_shape(
        self, model_id: str, seasonal: str, damped: bool
    ) -> None:
        adapter = create_adapter(model_id)
        assert adapter.seasonal == seasonal
        assert adapter.damped is damped

    def test_the_trend_is_always_additive(self) -> None:
        """`trend="add"` in both references, for all four variants."""
        frame = _dense(30)
        context = _context(min_history_profile="monthly_relaxed")
        adapter = create_adapter("exp_additive", context)
        adapter.fit(frame, context)
        assert adapter.parameter_metadata()["trend"] == "add"


class TestLstmConfiguration:
    def test_it_uses_meritons_layer_and_sodexos_early_stopping(self) -> None:
        frame = _dense(30)
        adapter = create_adapter("lstm", _context())
        adapter.fit(frame, _context())
        params = adapter.parameter_metadata()
        assert params["units"] == 64
        assert params["early_stopping"]["patience"] == 8
        assert params["early_stopping"]["restore_best_weights"] is True
        assert params["shuffle"] is False

    def test_recursion_does_not_consume_actuals_by_default(self) -> None:
        frame = _dense(34)
        adapter = create_adapter("lstm", _context())
        adapter.fit(frame.iloc[:28], _context())
        with_actuals = frame.iloc[28:].copy()
        blinded = with_actuals.copy()
        blinded["target"] = np.nan
        pd.testing.assert_series_equal(
            adapter.predict(with_actuals, _context()),
            adapter.predict(blinded, _context()),
        )

    def test_the_window_is_sized_from_available_history(self) -> None:
        adapter = create_adapter("lstm", _context())
        assert adapter._sequence_length_for(22) == 5
        assert adapter._sequence_length_for(100) == 12
        assert adapter._sequence_length_for(8) == 3


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

class TestPersistence:
    SAVEABLE = (
        "sarimax", "sarimax_exog", "var", "var_exog",
        "exp_additive", "exp_additive_damped",
    )

    @pytest.mark.parametrize("model_id", SAVEABLE)
    def test_a_reloaded_model_predicts_identically(
        self, model_id: str, tmp_path_factory
    ) -> None:
        """Neither reference persists a trained model at all; this is new work,
        so it gets a real round-trip test."""
        import tempfile

        frame = _dense(36)
        context = _context(min_history_profile="monthly_relaxed")
        adapter = create_adapter(model_id, context)
        adapter.fit(frame.iloc[:30], context)
        before = adapter.predict(frame.iloc[30:], context)

        destination = pd.Series([tempfile.mkdtemp()]).iloc[0]
        from pathlib import Path

        path = Path(destination) / model_id
        adapter.save(path)

        restored = create_adapter(model_id, context)
        restored.load(path)
        after = restored.predict(frame.iloc[30:], context)
        pd.testing.assert_series_equal(before, after)

    def test_xgboost_round_trips_through_its_native_format(self) -> None:
        import tempfile
        from pathlib import Path

        context = _context(xgboost_training_profile="fast")
        frame = _direct_frame()
        adapter = create_adapter("xgboost", context)
        adapter.fit(frame, context)
        before = adapter.predict(frame.head(9), context)

        path = Path(tempfile.mkdtemp()) / "xgb"
        adapter.save(path)
        assert path.with_suffix(".json").exists()

        restored = create_adapter("xgboost", context)
        restored.load(path)
        pd.testing.assert_series_equal(before, restored.predict(frame.head(9), context))


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

class TestCleanPredictions:
    def test_a_length_mismatch_raises_rather_than_padding(self) -> None:
        with pytest.raises(ValueError, match="Expected 6 predictions"):
            clean_predictions([1.0, 2.0], 6)

    def test_infinities_become_missing(self) -> None:
        cleaned = clean_predictions([1.0, np.inf, -np.inf], 3)
        assert cleaned.isna().sum() == 2

    def test_it_returns_a_reset_float_series(self) -> None:
        cleaned = clean_predictions(np.array([[1.0], [2.0]]), 2)
        assert list(cleaned.index) == [0, 1]
        assert str(cleaned.dtype) == "float64"


class TestSeasonalResolution:
    def test_the_reference_profile_only_considers_the_annual_cycle(self) -> None:
        resolution = resolve_seasonal_period(_dense(40)["target"], profile="reference")
        assert resolution.candidates_considered == (12,)
        assert resolution.period == 12

    def test_it_returns_none_when_no_candidate_fits(self) -> None:
        """The honest answer for AIS's 22-month window at period 12."""
        resolution = resolve_seasonal_period(_dense(22)["target"], profile="reference")
        assert resolution.period is None
        assert "two complete cycles" in resolution.rejected[12]

    def test_the_relaxed_profile_finds_a_shorter_cycle(self) -> None:
        resolution = resolve_seasonal_period(
            _dense(22)["target"], profile="monthly_relaxed"
        )
        assert resolution.period in {6, 4, 3}
        assert 12 in resolution.rejected

    def test_a_constant_series_resolves_to_nothing(self) -> None:
        flat = pd.Series([5.0] * 40)
        assert resolve_seasonal_period(flat, profile="reference").period is None

    def test_the_reference_length_can_be_the_smallest_fold(self) -> None:
        resolution = resolve_seasonal_period(
            _dense(40)["target"], profile="reference", reference_length=20
        )
        assert resolution.period is None
        assert resolution.reference_length == 20

    def test_smallest_fold_size_subtracts_every_validation_block(self) -> None:
        assert smallest_fold_train_size(40, folds=3, validation_size=6) == 22
        # Never returns a non-positive size.
        assert smallest_fold_train_size(10, folds=3, validation_size=6) == 10


class TestFutureKnownExog:
    def test_only_calendar_features_are_derived(self) -> None:
        frame = attach_calendar_exog(_series([1.0] * 12)[["series_id", "period_index"]])
        for column in CALENDAR_EXOG_COLUMNS:
            assert column in frame.columns

    def test_the_month_encoding_is_cyclical(self) -> None:
        """A raw month number tells a linear model December is far from January."""
        frame = attach_calendar_exog(
            pd.DataFrame({"period_index": [24_299, 24_300]})  # Dec then Jan
        )
        assert frame["calendar_month"].tolist() == [12, 1]
        gap = abs(frame["month_sin"].diff().iloc[1]) + abs(frame["month_cos"].diff().iloc[1])
        assert gap < 1.0

    def test_no_historical_driver_is_offered_as_future_known(self) -> None:
        frame = _dense(24)
        frame["mean_mrp"] = 100.0
        frame["despatched_qty"] = 5.0
        resolved = resolve_exog_columns(frame, include_static=True)
        assert "mean_mrp" not in resolved
        assert "despatched_qty" not in resolved

    def test_static_attributes_are_included_only_on_request(self) -> None:
        frame = _dense(24)
        frame["region"] = "NORTH-1"
        assert "region" not in resolve_exog_columns(frame)
        assert "region" in resolve_exog_columns(frame, include_static=True)

    def test_preparing_a_frame_returns_its_own_exog_set(self) -> None:
        prepared, columns = prepare_local_series_frame(
            _series([1.0] * 12)[["series_id", "period_index", "target"]]
        )
        assert set(columns) <= set(prepared.columns)
        assert columns == CALENDAR_EXOG_COLUMNS

    def test_a_missing_period_column_raises_rather_than_guessing(self) -> None:
        with pytest.raises(KeyError, match="period_index"):
            attach_calendar_exog(pd.DataFrame({"target": [1.0]}))
