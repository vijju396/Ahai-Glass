"""Metrics, folds, baselines, segmentation and quantile calibration.

The decisive tests here are the ones that would catch a *plausible* wrong
answer rather than a crash:

- `test_reference_metrics_match_an_independent_transcription` re-implements the
  reference algorithm from the reference source inside the test, so parity is
  checked against Meriton/Sodexo rather than against our own port.
- The `Undefined` class asserts that a metric with no defined value comes back
  `None` with a stated reason - never 0, never 100, never a sentinel.
- `test_mase_denominator_ignores_the_validation_window` corrupts the validation
  actuals and asserts MASE's benchmark does not move.
"""

from __future__ import annotations

import math
from statistics import mean

import numpy as np
import pandas as pd
import pytest

from app.ml.evaluation.baselines import forecast_all_baselines, forecast_baseline
from app.ml.evaluation.folds import (
    MIN_TRAIN_PERIODS,
    Origin,
    aggregate_test_points,
    build_origins,
    fast_holdout_origin,
    mandated_origins,
    smallest_fold_train_size,
)
from app.ml.evaluation.metrics import (
    QUANTILE_LEVELS,
    REFERENCE_METRIC_KEYS,
    evaluate,
    is_valid_metric,
    reference_metrics,
)
from app.ml.evaluation.quantiles import (
    MIN_RESIDUALS,
    POOLING_LEVELS,
    ResidualStore,
    apply_calibration,
    conformal_minimum,
)
from app.ml.evaluation.segmentation import (
    ADI_CUTOFF,
    CV_SQUARED_CUTOFF,
    DemandSegment,
    profile_panel,
    profile_series,
    segment_counts,
)
from app.ml.features.panel import month_index

PANEL_START = month_index("2024-04")
PANEL_END = month_index("2026-07")


# ----------------------------------------------------------------------
# Reference parity
# ----------------------------------------------------------------------


def _transcribed_reference(actuals, predictions):
    """Meriton `metrics_service.py:7-41` / Sodexo `metrics.py:9-43`.

    Transcribed from the reference source into the test, deliberately not
    importing our implementation. If our port drifts, this disagrees.
    """

    def to_float(value):
        if value is None:
            return None
        try:
            if math.isnan(float(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    pairs = []
    for actual, predicted in zip(actuals, predictions):
        a, p = to_float(actual), to_float(predicted)
        if a is not None and p is not None:
            pairs.append((a, p))
    if not pairs:
        return {k: None for k in ("mape", "accuracy", "mae", "rmse", "wape", "bias")}
    abs_errors = [abs(a - p) for a, p in pairs]
    squared = [(a - p) ** 2 for a, p in pairs]
    nonzero = [(a, p) for a, p in pairs if a != 0]
    total = sum(a for a, _ in pairs)
    mape = mean(abs((a - p) / a) for a, p in nonzero) * 100 if nonzero else None
    mae = mean(abs_errors)
    rmse = math.sqrt(mean(squared))
    wape = (sum(abs_errors) / total * 100) if total else None
    bias = (sum(p - a for a, p in pairs) / total * 100) if total else None
    accuracy = max(100 - mape, 0) if mape is not None else None

    def r(v):
        return round(v, 2) if v is not None else None

    return {
        "mape": r(mape),
        "accuracy": r(accuracy),
        "mae": r(mae),
        "rmse": r(rmse),
        "wape": r(wape),
        "bias": r(bias),
    }


class TestReferenceParity:
    @pytest.mark.parametrize(
        "actuals,predictions",
        [
            ([10, 20, 30], [11, 19, 33]),
            ([0, 0, 5], [1, 0, 4]),
            ([0, 0, 0], [1, 2, 3]),
            ([5, None, 7], [4, 6, float("nan")]),
            ([12], [12]),
            ([-4, 9, 2], [1, 8, 2]),
            ([], []),
        ],
    )
    def test_reference_metrics_match_an_independent_transcription(
        self, actuals, predictions
    ):
        assert reference_metrics(actuals, predictions) == _transcribed_reference(
            actuals, predictions
        )

    def test_every_reference_key_is_present_even_when_undefined(self):
        result = reference_metrics([], [])
        assert set(result) == set(REFERENCE_METRIC_KEYS)
        assert all(value is None for value in result.values())

    def test_reference_accuracy_is_a_mape_restatement(self):
        result = reference_metrics([100, 100], [90, 110])
        assert result["mape"] == 10.0
        assert result["accuracy"] == 90.0

    def test_reference_coercion_keeps_infinity_as_the_references_do(self):
        # Both references reject NaN but not inf. Parity means reproducing that,
        # so an infinite prediction reaches MAE rather than being dropped.
        result = reference_metrics([10, 10], [10, float("inf")])
        assert result["mae"] == float("inf")

    def test_our_own_evaluate_rejects_infinity(self):
        # The AIS metric set treats inf as unusable, which is the opposite
        # choice and the deliberate one.
        metrics = evaluate([10, 10], [10, float("inf")])
        assert metrics.points == 1
        assert metrics.dropped_points == 1
        assert metrics.mae == 0.0

    def test_is_valid_metric_rejects_a_failed_row(self):
        assert not is_valid_metric({"status": "FAILED", "mape": 1, "mae": 1, "rmse": 1})
        assert is_valid_metric({"status": "completed", "mape": 1, "mae": 1, "rmse": 1})

    def test_is_valid_metric_rejects_an_undefined_mape(self):
        # The reason the legacy ranking is separately labelled: an intermittent
        # series has no MAPE and so cannot enter it at all.
        assert not is_valid_metric({"mape": None, "mae": 1, "rmse": 1})


# ----------------------------------------------------------------------
# Undefined values
# ----------------------------------------------------------------------


class TestUndefined:
    def test_an_all_zero_window_has_no_wape_and_says_why(self):
        metrics = evaluate([0, 0, 0], [2, 1, 0])
        assert metrics.wape is None
        assert metrics.bias is None
        assert "undefined" in metrics.undefined["wape"]
        # MAE is still defined: an absolute error needs no denominator.
        assert metrics.mae == pytest.approx(1.0)

    def test_an_all_zero_window_has_no_mape(self):
        metrics = evaluate([0, 0], [1, 1])
        assert metrics.mape is None
        assert metrics.accuracy is None
        assert "mape" in metrics.undefined

    def test_a_constant_training_window_has_no_mase(self):
        metrics = evaluate([5, 6], [5, 5], insample_actuals=[4, 4, 4, 4])
        assert metrics.mase is None
        assert "undefined rather than infinite" in metrics.undefined["mase"]

    def test_mase_needs_an_insample_window(self):
        assert evaluate([5, 6], [5, 5]).mase is None

    def test_no_usable_pair_reports_it_rather_than_returning_zeros(self):
        metrics = evaluate([None, float("nan")], [1, 2])
        assert metrics.points == 0
        assert metrics.mae is None
        assert metrics.undefined["all"]

    def test_zero_actuals_are_counted_not_hidden(self):
        metrics = evaluate([0, 4, 0, 6], [1, 4, 1, 6])
        assert metrics.zero_actual_points == 2
        assert metrics.points == 4


class TestMetricMath:
    def test_wape_uses_absolute_actuals_so_cancellation_cannot_inflate_it(self):
        # The references divide by the signed sum, which cancellation can drive
        # toward zero. With non-negative actuals the two agree exactly, which is
        # what makes this a robustness change rather than a different metric.
        metrics = evaluate([10, 20, 30], [11, 19, 33])
        legacy = reference_metrics([10, 20, 30], [11, 19, 33])
        assert metrics.wape == pytest.approx(legacy["wape"], abs=0.01)

        signed_cancelling = evaluate([-10, 10], [0, 0])
        assert signed_cancelling.wape == pytest.approx(100.0)
        assert reference_metrics([-10, 10], [0, 0])["wape"] is None

    def test_smape_treats_a_zero_forecast_of_zero_demand_as_correct(self):
        # Not dropped: on an intermittent series most months are zero, and
        # dropping them would exclude the majority of the window.
        assert evaluate([0, 0], [0, 0]).smape == pytest.approx(0.0)

    def test_smape_is_bounded_at_200_percent(self):
        assert evaluate([0, 0], [5, 9]).smape == pytest.approx(200.0)

    def test_mase_denominator_ignores_the_validation_window(self):
        insample = [10, 12, 11, 14, 13]
        first = evaluate([20, 20], [18, 18], insample_actuals=insample)
        # Corrupt the validation actuals beyond recognition; the benchmark is
        # computed from the training window and must not move.
        second = evaluate([9999, -9999], [18, 18], insample_actuals=insample)
        assert first.naive_mae == second.naive_mae

    def test_mase_below_one_means_better_than_naive(self):
        insample = [10, 20, 10, 20, 10, 20]  # naive MAE 10
        metrics = evaluate([20, 20], [19, 21], insample_actuals=insample)
        assert metrics.naive_mae == pytest.approx(10.0)
        assert metrics.mase == pytest.approx(0.1)

    def test_mase_uses_the_seasonal_lag_when_a_period_is_supplied(self):
        insample = [1, 5, 1, 5, 1, 5, 1, 5]
        plain = evaluate([1], [1], insample_actuals=insample)
        seasonal = evaluate([1], [1], insample_actuals=insample, seasonal_period=2)
        assert plain.naive_mae == pytest.approx(4.0)
        # At lag 2 the series repeats exactly, so the seasonal benchmark is
        # perfect and the ratio is undefined rather than infinite.
        assert seasonal.naive_mae == pytest.approx(0.0)
        assert seasonal.mase is None

    def test_bias_sign_distinguishes_over_from_under_forecasting(self):
        over = evaluate([10, 10], [12, 12])
        under = evaluate([10, 10], [8, 8])
        assert over.bias > 0
        assert under.bias < 0
        assert over.bias_abs == pytest.approx(under.bias_abs)

    def test_censored_points_are_scored_but_counted(self):
        metrics = evaluate([10, 10], [9, 9], censored=[True, False])
        assert metrics.points == 2
        assert metrics.censored_points == 1

    def test_pinball_penalises_a_shortfall_harder_at_a_deeper_quantile(self):
        # An actual above the quantile is the service-level failure, so the
        # penalty must grow with the level.
        q80 = evaluate([100], [50], quantile_predictions={0.80: [60]})
        q95 = evaluate([100], [50], quantile_predictions={0.95: [60]})
        assert q95.pinball["q95"] > q80.pinball["q80"]

    def test_coverage_counts_actuals_at_or_below_the_quantile(self):
        metrics = evaluate(
            [1, 2, 3, 4], [1, 1, 1, 1], quantile_predictions={0.80: [2, 2, 2, 2]}
        )
        assert metrics.coverage["q80"] == pytest.approx(50.0)

    def test_a_quantile_series_of_the_wrong_length_is_reported_not_guessed(self):
        metrics = evaluate([1, 2], [1, 2], quantile_predictions={0.90: [1]})
        assert "q90" in metrics.undefined
        assert "q90" not in metrics.coverage


# ----------------------------------------------------------------------
# Folds
# ----------------------------------------------------------------------


class TestFolds:
    def test_the_mandated_origins_are_what_the_architecture_says(self):
        origins = mandated_origins(PANEL_START, PANEL_END)
        assert [o.name for o in origins] == ["primary", "second"]
        primary, second = origins
        assert primary.train_end_period == "2025-09"
        assert primary.validation_periods == (
            "2025-10",
            "2025-11",
            "2025-12",
            "2026-01",
            "2026-02",
            "2026-03",
        )
        assert second.train_end_period == "2026-01"
        assert second.validation_periods[-1] == "2026-07"

    def test_the_primary_origin_trains_on_eighteen_months_not_twenty_two(self):
        # 22 is the trailing-holdout figure (train through 2026-01). Conflating
        # the two misstates how much history the mandated cut actually leaves.
        primary, second = mandated_origins(PANEL_START, PANEL_END)
        assert primary.train_periods == 18
        assert second.train_periods == 22

    def test_default_is_the_mandated_pair_only(self):
        origins = build_origins(PANEL_START, PANEL_END)
        assert [o.name for o in origins] == ["primary", "second"]
        assert all(o.mandated for o in origins)

    def test_a_third_origin_adds_test_periods_but_not_distinct_ones(self):
        two = build_origins(PANEL_START, PANEL_END, max_origins=2)
        three = build_origins(PANEL_START, PANEL_END, max_origins=3)
        assert len(three) == 3
        assert aggregate_test_points(two) == (12, 10)
        # Six more test periods, not one more distinct month: the reason the
        # default stops at two.
        assert aggregate_test_points(three) == (18, 12)

    def test_the_mandated_windows_overlap_and_the_count_shows_it(self):
        total, distinct = aggregate_test_points(build_origins(PANEL_START, PANEL_END))
        assert total == 12
        assert distinct == 10
        assert total != distinct

    def test_origins_are_ordered_oldest_first_with_dense_fold_indices(self):
        origins = build_origins(PANEL_START, PANEL_END, max_origins=3)
        assert [o.fold_index for o in origins] == [0, 1, 2]
        ends = [o.train_end_index for o in origins]
        assert ends == sorted(ends)

    def test_a_panel_too_short_for_any_honest_origin_returns_nothing(self):
        short_end = PANEL_START + 4
        assert build_origins(PANEL_START, short_end) == []

    def test_a_mandate_the_panel_cannot_satisfy_is_dropped_not_truncated(self):
        # Panel ends 2026-02, so the primary origin's window (to 2026-03) does
        # not fit. It must be absent rather than silently shortened.
        origins = mandated_origins(PANEL_START, month_index("2026-02"))
        assert [o.name for o in origins] == []

    def test_min_train_periods_is_one_annual_cycle(self):
        assert MIN_TRAIN_PERIODS == 12

    def test_an_origin_below_the_training_floor_is_refused(self):
        start = month_index("2025-01")
        assert mandated_origins(start, PANEL_END) == [
            o for o in mandated_origins(start, PANEL_END) if o.train_periods >= 12
        ]
        primary = [o for o in mandated_origins(start, PANEL_END) if o.name == "primary"]
        assert not primary  # 2025-01..2025-09 is 9 months, below the floor

    def test_horizon_of_maps_a_period_to_its_step_ahead(self):
        primary = mandated_origins(PANEL_START, PANEL_END)[0]
        assert primary.horizon_of(month_index("2025-10")) == 1
        assert primary.horizon_of(month_index("2026-03")) == 6
        assert primary.horizon_of(month_index("2026-04")) is None
        assert primary.horizon_of(month_index("2025-09")) is None

    def test_fast_holdout_takes_the_origin_with_most_training_history(self):
        origins = build_origins(PANEL_START, PANEL_END)
        chosen = fast_holdout_origin(origins)
        assert chosen is not None
        assert chosen.name == "second"
        assert chosen.train_periods == max(o.train_periods for o in origins)

    def test_fast_holdout_of_nothing_is_none_not_a_crash(self):
        assert fast_holdout_origin([]) is None

    def test_smallest_fold_train_size_is_re_exported_not_redefined(self):
        from app.ml.evaluation import seasonality

        assert seasonality.smallest_fold_train_size is smallest_fold_train_size

    def test_origin_dict_is_reportable(self):
        payload = mandated_origins(PANEL_START, PANEL_END)[0].as_dict()
        assert payload["train_end_period"] == "2025-09"
        assert payload["train_periods"] == 18
        assert payload["horizon"] == 6
        assert payload["mandated"] is True


# ----------------------------------------------------------------------
# Baselines
# ----------------------------------------------------------------------


class TestBaselines:
    def test_naive_repeats_the_last_observation(self):
        result = forecast_baseline("naive", [1, 2, 7], 3)
        assert result.values == [7.0, 7.0, 7.0]
        assert result.fallback_reason is None

    def test_seasonal_naive_repeats_the_last_cycle(self):
        result = forecast_baseline(
            "seasonal_naive", [1, 2, 3, 4, 5, 6], 4, seasonal_period=3
        )
        assert result.values == [4.0, 5.0, 6.0, 4.0]
        assert result.applied_method == "seasonal_naive_3"

    def test_seasonal_naive_without_a_cycle_falls_back_to_naive_not_zero(self):
        # A fallback to zero would read as a confident forecast of no demand,
        # which is a far stronger and more damaging claim.
        result = forecast_baseline("seasonal_naive", [4, 9], 2, seasonal_period=12)
        assert result.values == [9.0, 9.0]
        assert result.applied_method == "naive"
        assert "only 2 are available" in result.fallback_reason

    def test_moving_averages_use_their_window(self):
        assert forecast_baseline("ma3", [1, 2, 3, 9, 9, 9], 1).values == [9.0]
        assert forecast_baseline("ma6", [0, 0, 0, 3, 3, 3], 1).values == [1.5]

    def test_a_short_window_narrows_the_average_and_says_so(self):
        result = forecast_baseline("ma6", [4, 8], 1)
        assert result.values == [6.0]
        assert result.applied_method == "ma2"
        assert "only 2 observations" in result.fallback_reason

    def test_an_empty_history_yields_no_forecast_rather_than_zero(self):
        result = forecast_baseline("naive", [], 3)
        assert all(math.isnan(v) for v in result.values)
        assert "rather than zero" in result.fallback_reason

    def test_all_zero_history_forecasts_zero_which_is_a_real_answer(self):
        # Distinct from the empty case above: these are observed true zeros.
        result = forecast_baseline("naive", [0, 0, 0], 2)
        assert result.values == [0.0, 0.0]
        assert result.fallback_reason is None

    def test_a_registered_model_id_is_refused(self):
        with pytest.raises(ValueError, match="not a baseline method"):
            forecast_baseline("sarimax", [1, 2, 3], 1)

    def test_all_four_baselines_are_produced_in_registry_order(self):
        result = forecast_all_baselines([1, 2, 3, 4, 5, 6, 7], 2, seasonal_period=3)
        assert list(result) == ["naive", "seasonal_naive", "ma3", "ma6"]

    def test_baselines_never_overlap_the_thirteen(self):
        from app.ml.registry.canonical_models import (
            BASELINE_METHOD_IDS,
            CANONICAL_MODEL_IDS,
        )

        assert not set(BASELINE_METHOD_IDS) & set(CANONICAL_MODEL_IDS)


# ----------------------------------------------------------------------
# Segmentation
# ----------------------------------------------------------------------


class TestSegmentation:
    def test_a_steady_series_is_smooth(self):
        assert profile_series([10, 11, 9, 10, 12, 10]).segment is DemandSegment.SMOOTH

    def test_a_sparse_variable_series_is_lumpy(self):
        profile = profile_series([0, 0, 50, 0, 0, 1, 0, 0, 90])
        assert profile.adi >= ADI_CUTOFF
        assert profile.cv_squared >= CV_SQUARED_CUTOFF
        assert profile.segment is DemandSegment.LUMPY

    def test_an_all_zero_series_is_no_demand_with_undefined_adi(self):
        profile = profile_series([0, 0, 0])
        assert profile.segment is DemandSegment.NO_DEMAND
        assert profile.adi is None  # not infinity, not zero

    def test_one_nonzero_month_is_single_event_not_intermittent(self):
        # CV-squared needs two non-zero observations. Calling this
        # `intermittent` would imply a dispersion nobody measured.
        profile = profile_series([0, 0, 7, 0])
        assert profile.segment is DemandSegment.SINGLE_EVENT
        assert profile.cv_squared is None
        assert profile.adi == pytest.approx(4.0)

    def test_cv_squared_uses_only_nonzero_values(self):
        # Over all months the zeros would inflate dispersion and reclassify most
        # of the panel as lumpy.
        profile = profile_series([0, 10, 0, 10, 0, 10])
        assert profile.cv_squared == pytest.approx(0.0)
        assert profile.segment is DemandSegment.INTERMITTENT

    def test_the_vectorised_panel_pass_agrees_with_the_definition(self):
        frame = pd.DataFrame(
            {
                "series_id": ["a"] * 6 + ["b"] * 6 + ["c"] * 4,
                "target": [10, 11, 9, 10, 12, 10] + [0, 0, 5, 0, 0, 90] + [0, 0, 0, 0],
            }
        )
        vectorised = profile_panel(frame).set_index("series_id")
        for series_id, group in frame.groupby("series_id"):
            expected = profile_series(group["target"])
            assert vectorised.loc[series_id, "segment"] == expected.segment.value
            assert vectorised.loc[series_id, "nonzero_months"] == expected.nonzero_months

    def test_segment_counts_report_every_label_including_zero(self):
        frame = pd.DataFrame({"series_id": ["a"] * 3, "target": [1, 1, 1]})
        counts = segment_counts(profile_panel(frame))
        assert set(counts) == {segment.value for segment in DemandSegment}
        assert counts["lumpy"] == 0

    def test_an_empty_panel_profiles_to_an_empty_frame(self):
        assert profile_panel(pd.DataFrame({"series_id": [], "target": []})).empty


# ----------------------------------------------------------------------
# Quantile calibration
# ----------------------------------------------------------------------


class TestQuantiles:
    def test_conformal_minimum_is_the_order_statistic_condition(self):
        for level in QUANTILE_LEVELS:
            n = conformal_minimum(level)
            assert math.ceil((n + 1) * level) <= n
            assert math.ceil(n * level) > n - 1  # n - 1 would not suffice

    def test_conformal_minimum_is_not_off_by_one_from_float_error(self):
        # `0.8 / (1 - 0.8)` is 4.000000000000001 in binary floating point, so
        # the closed form would demand 5 residuals at q80 instead of 4.
        assert conformal_minimum(0.80) == 4
        assert conformal_minimum(0.90) == 9
        assert conformal_minimum(0.95) == 19

    def test_a_dense_cell_calibrates_conformally_at_the_finest_pool(self):
        store = ResidualStore()
        rng = np.random.default_rng(3)
        actuals = rng.poisson(20, 40).astype(float)
        store.add("xgboost", 1, "smooth", actuals, actuals - rng.normal(0, 3, 40))
        calibration = store.calibrate("xgboost", 1, "smooth")
        for offset in calibration.offsets.values():
            assert offset.method == "conformal"
            assert offset.pooling_level == "model_horizon_segment"
            assert offset.offset is not None

    def test_a_thin_cell_labels_the_deeper_quantiles_as_interpolated(self):
        store = ResidualStore()
        store.add("lstm", 3, "lumpy", [10, 12, 9, 11, 13, 10], [8, 9, 9, 10, 11, 9])
        offsets = store.calibrate("lstm", 3, "lumpy").offsets
        assert offsets["q80"].method == "conformal"
        assert offsets["q90"].method == "empirical"
        assert offsets["q95"].method == "empirical"
        assert "interpolates the tail" in offsets["q95"].note

    def test_below_the_five_residual_floor_no_interval_is_offered(self):
        store = ResidualStore()
        store.add("var", 2, "smooth", [5, 6], [4, 5])
        offsets = store.calibrate("var", 2, "smooth").offsets
        assert all(offset.offset is None for offset in offsets.values())
        assert all(offset.method == "none" for offset in offsets.values())
        assert "fabricated band" in offsets["q95"].note

    def test_a_sparse_cell_falls_back_to_a_coarser_pool_and_records_it(self):
        store = ResidualStore()
        # One residual in the target cell; plenty elsewhere at the same horizon.
        store.add("sarimax", 4, "lumpy", [10], [9])
        store.add("sarimax", 4, "smooth", list(range(20)), [x + 1 for x in range(20)])
        offset = store.calibrate("sarimax", 4, "lumpy").offsets["q80"]
        assert offset.pooling_level == "model_horizon"
        assert offset.residual_count == 21

    def test_the_pooling_chain_runs_finest_to_coarsest(self):
        assert POOLING_LEVELS[0] == "model_horizon_segment"
        assert POOLING_LEVELS[-1] == "global"

    def test_residuals_are_actual_minus_prediction(self):
        # Sign matters: a positive residual must mean under-forecasting, or the
        # upper quantiles would be built from the wrong tail.
        store = ResidualStore()
        store.add("var", 1, "smooth", [10] * 6, [8] * 6)
        offset = store.calibrate("var", 1, "smooth").offsets["q80"]
        assert offset.offset == pytest.approx(2.0)

    def test_quantiles_are_monotone_and_crossings_are_counted(self):
        store = ResidualStore()
        store.add("lstm", 3, "lumpy", [10, 12, 9, 11, 13, 10], [8, 9, 9, 10, 11, 9])
        calibration = store.calibrate("lstm", 3, "lumpy")
        # This calibration genuinely crosses - q80 conformal exceeds q90
        # interpolated - which is why the correction has to be counted.
        raw = [calibration.offsets[key].offset for key in ("q80", "q90", "q95")]
        assert raw != sorted(raw)
        quantiles, report = apply_calibration([10.0, 10.0], calibration)
        assert quantiles["q80"] <= quantiles["q90"] <= quantiles["q95"]
        assert report.crossings_corrected == 2
        assert report.rows == 2

    def test_no_quantile_falls_below_the_point_forecast(self):
        store = ResidualStore()
        store.add("var", 1, "smooth", [5] * 8, [9] * 8)  # every residual negative
        calibration = store.calibrate("var", 1, "smooth")
        quantiles, _ = apply_calibration([10.0], calibration)
        assert all(values[0] >= 10.0 for values in quantiles.values())

    def test_quantiles_are_floored_at_zero(self):
        store = ResidualStore()
        store.add("var", 1, "smooth", [0] * 8, [5] * 8)
        calibration = store.calibrate("var", 1, "smooth")
        quantiles, _ = apply_calibration([0.0], calibration, floor_at_zero=True)
        assert all(values[0] >= 0.0 for values in quantiles.values())

    def test_a_missing_point_forecast_yields_no_quantiles(self):
        store = ResidualStore()
        store.add("var", 1, "smooth", [5] * 8, [4] * 8)
        calibration = store.calibrate("var", 1, "smooth")
        quantiles, report = apply_calibration([None], calibration)
        assert quantiles["q80"] == [None]
        assert report.rows == 1

    def test_unusable_residual_pairs_are_not_recorded(self):
        store = ResidualStore()
        added = store.add("var", 1, "smooth", [1, None, float("nan")], [1, 2, 3])
        assert added == 1
        assert store.count("var", 1, "smooth") == 1

    def test_the_minimum_matches_both_references(self):
        assert MIN_RESIDUALS == 5
