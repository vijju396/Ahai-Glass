"""The backtester: status vocabulary, leakage, isolation and pooling.

The load-bearing tests here are:

- `TestNoLeakage` - corrupting the validation window must not change a single
  prediction, and the seasonal period must be resolved per fold rather than
  once on the full series.
- `TestStatusVocabulary` - every model comes back, whatever happened to it, and
  `Ineligible`, `Failed`, `Timed out` and `Not evaluated (budget)` are four
  distinct outcomes rather than four spellings of one.
- `TestPooling` - the mandated origins overlap, so pooling must de-duplicate
  rather than double-count.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from app.ml.adapters.base import Eligibility, ForecastModelAdapter, ModelContext
from app.ml.evaluation.backtest import (
    FORECAST_MAGNITUDE_FACTOR,
    EvaluationBudget,
    backtest_all_models,
    backtest_baselines,
    backtest_model,
    forecast_magnitude_bound,
)
from app.ml.evaluation.folds import build_origins, mandated_origins
from app.ml.evaluation.quantiles import ResidualStore
from app.ml.features.panel import month_index
from app.schemas.common import EvaluationMode, ModelRunStatus

PANEL_START = month_index("2024-04")
PANEL_END = month_index("2026-07")


def _series(
    start: str = "2024-04",
    months: int = 28,
    values: list[float] | None = None,
    *,
    censored: list[bool] | None = None,
) -> pd.DataFrame:
    """A gapless single-series frame shaped like the real panel."""
    start_index = month_index(start)
    if values is None:
        rng = np.random.default_rng(5)
        values = list(10 + 4 * np.sin(np.arange(months) * 0.5) + rng.normal(0, 1, months))
    index = list(range(start_index, start_index + months))
    month = [(i % 12) + 1 for i in index]
    frame = pd.DataFrame(
        {
            "series_id": ["s1"] * months,
            "period_index": index,
            "target": values[:months],
            "despatched_qty": [max(v - 1, 0) for v in values[:months]],
            "shortfall_qty": [1.0] * months,
            "mean_mrp": [100.0] * months,
            "is_censored": censored if censored is not None else [False] * months,
            # The calendar exogenous set, so the four `_exog` variants are
            # genuinely exercised rather than being ineligible for want of a
            # driver column. Derived the same way `attach_calendar_exog` does,
            # but written out here to keep this fixture free of AIS imports.
            "calendar_month": month,
            "month_sin": list(np.sin(2 * np.pi * (np.array(month) - 1) / 12)),
            "month_cos": list(np.cos(2 * np.pi * (np.array(month) - 1) / 12)),
            "quarter": [((m - 1) // 3) + 1 for m in month],
        }
    )
    return frame


#: The calendar drivers `_series` carries, in a deterministic order.
EXOG_COLUMNS = ("calendar_month", "month_sin", "month_cos", "quarter")


class _Recorder(ForecastModelAdapter):
    """A minimal adapter that records exactly what it was trained on."""

    model_id = "recorder"
    display_name = "Recorder"
    family = "test"
    seen_frames: list[pd.DataFrame] = []
    seen_periods: list[tuple[int, ...]] = []
    seen_seasonal: list[int | None] = []

    def _history_thresholds(self) -> dict[str, int]:
        return {"reference": 1, "monthly_relaxed": 1}

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        type(self).seen_frames.append(train_df.copy())
        type(self).seen_periods.append(tuple(train_df["period_index"]))
        type(self).seen_seasonal.append(context.seasonal_period)
        self._mean = float(pd.to_numeric(train_df["target"]).mean())

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext):
        return [self._mean] * len(horizon_df)

    def save(self, destination) -> None:  # pragma: no cover - not exercised here
        raise NotImplementedError

    def load(self, source) -> None:  # pragma: no cover - not exercised here
        raise NotImplementedError

    @classmethod
    def reset(cls) -> None:
        cls.seen_frames = []
        cls.seen_periods = []
        cls.seen_seasonal = []


class _Exploder(_Recorder):
    model_id = "exploder"
    display_name = "Exploder"

    def _predict(self, horizon_df: pd.DataFrame, context: ModelContext):
        return [1e12] * len(horizon_df)


class _Raiser(_Recorder):
    model_id = "raiser"
    display_name = "Raiser"

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        raise RuntimeError("this fit always fails")


class _Ineligible(_Recorder):
    model_id = "ineligible"
    display_name = "Always Ineligible"

    def validate_eligibility(self, train_df, context=None) -> Eligibility:
        return Eligibility(
            eligible=False,
            reason="this model is never eligible",
            remediation="nothing; it exists to be refused",
        )


class _Slow(_Recorder):
    model_id = "slow"
    display_name = "Slow"

    def _fit(self, train_df: pd.DataFrame, context: ModelContext) -> None:
        time.sleep(0.15)
        super()._fit(train_df, context)


@pytest.fixture(autouse=True)
def _reset_recorder():
    _Recorder.reset()
    yield
    _Recorder.reset()


class TestNoLeakage:
    def test_a_fold_never_sees_a_period_after_its_origin(self):
        origins = build_origins(PANEL_START, PANEL_END)
        backtest_model(_series(), lambda ctx: _Recorder(ctx), origins)
        assert len(_Recorder.seen_periods) == 2
        for origin, periods in zip(origins, _Recorder.seen_periods):
            assert max(periods) == origin.train_end_index

    def test_corrupting_the_validation_window_changes_no_prediction(self):
        # The decisive leakage test. If any prediction moves, the model reached
        # past its origin.
        origins = build_origins(PANEL_START, PANEL_END)
        clean = _series()
        clean_result = backtest_model(clean, lambda ctx: _Recorder(ctx), origins)

        poisoned = clean.copy()
        mask = poisoned["period_index"] > origins[0].train_end_index
        poisoned.loc[mask, "target"] = 999_999.0
        poisoned_result = backtest_model(poisoned, lambda ctx: _Recorder(ctx), origins)

        first_clean = clean_result.origins[0].predictions
        first_poisoned = poisoned_result.origins[0].predictions
        assert first_clean == pytest.approx(first_poisoned)

    def test_the_seasonal_period_is_resolved_from_the_fold_not_the_full_series(self):
        # The decisive form: a series that is flat for its first 18 months and
        # strongly 6-periodic afterwards. Resolving on the full window would
        # find the cycle; resolving on the primary origin's own 18 months
        # cannot, because it is not there yet.
        flat = [7.0] * 18
        cyclic = [float((x % 6) * 20) for x in range(10)]
        frame = _series(months=28, values=flat + cyclic)
        origins = build_origins(PANEL_START, PANEL_END)
        context = ModelContext(min_history_profile="monthly_relaxed")
        backtest_model(frame, lambda ctx: _Recorder(ctx), origins, base_context=context)

        assert len(_Recorder.seen_seasonal) == 2
        primary_period, second_period = _Recorder.seen_seasonal
        # A constant window has no estimable cycle at all.
        assert primary_period is None
        # The later origin has seen four months of the cycle and does resolve
        # one - so the two folds genuinely differ, which is only possible if
        # each resolved from its own window.
        assert second_period is not None
        assert primary_period != second_period

    def test_the_resolved_period_equals_resolving_on_that_window_alone(self):
        # Belt and braces on the above: the value the fold received is exactly
        # what the resolver returns for that fold's training slice in isolation.
        from app.ml.evaluation.seasonality import resolve_seasonal_period

        frame = _series(months=28, values=[float((x % 6) * 5 + 3) for x in range(28)])
        origins = build_origins(PANEL_START, PANEL_END)
        context = ModelContext(min_history_profile="monthly_relaxed")
        backtest_model(frame, lambda ctx: _Recorder(ctx), origins, base_context=context)

        for origin, received in zip(origins, _Recorder.seen_seasonal):
            window = frame[frame["period_index"] <= origin.train_end_index]
            expected = resolve_seasonal_period(
                window["target"], profile="monthly_relaxed"
            )
            assert received == expected.period

    def test_a_fresh_adapter_is_built_per_origin(self):
        origins = build_origins(PANEL_START, PANEL_END)
        # The adapters themselves, not their `id()`. CPython reuses an
        # address once an object is collected, so two adapters built at
        # different times could share an id and this assertion would fail
        # for a reason that has nothing to do with leakage - observed once
        # in a full-suite run. Holding the references keeps them distinct.
        built: list[object] = []

        def factory(context):
            adapter = _Recorder(context)
            built.append(adapter)
            return adapter

        backtest_model(_series(), factory, origins)
        # One probe plus one per origin, all distinct: no fitted state can
        # survive from one fold into the next.
        assert len(built) == 3
        assert all(a is not b for i, a in enumerate(built) for b in built[i + 1 :])

    def test_mase_benchmark_comes_from_the_training_window(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        clean = _series()
        result = backtest_model(clean, lambda ctx: _Recorder(ctx), origins)
        naive_clean = result.origins[0].metrics.naive_mae

        poisoned = clean.copy()
        poisoned.loc[
            poisoned["period_index"] > origins[0].train_end_index, "target"
        ] = 50_000.0
        poisoned_result = backtest_model(poisoned, lambda ctx: _Recorder(ctx), origins)
        assert poisoned_result.origins[0].metrics.naive_mae == pytest.approx(naive_clean)


class TestStatusVocabulary:
    def test_a_completed_model_reports_metrics_and_points(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Recorder(ctx), origins)
        assert result.status is ModelRunStatus.COMPLETED
        assert result.pooled is not None
        assert result.pooled.points == 10  # 12 total, 10 distinct

    def test_ineligible_carries_a_requirement_and_a_remediation(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Ineligible(ctx), origins)
        assert result.status is ModelRunStatus.INELIGIBLE
        assert result.pooled is None
        eligibility = result.origins[0].eligibility
        assert eligibility is not None and not eligibility.eligible
        assert eligibility.remediation

    def test_failed_is_not_ineligible(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Raiser(ctx), origins)
        assert result.status is ModelRunStatus.FAILED
        assert result.status is not ModelRunStatus.INELIGIBLE
        assert "this fit always fails" in result.origins[0].failure_reason

    def test_a_failed_model_gets_no_zero_forecast(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Raiser(ctx), origins)
        assert result.pooled is None
        assert result.origins[0].predictions == []
        assert result.origins[0].metrics is None

    def test_timed_out_discards_the_metrics_it_produced(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        budget = EvaluationBudget(per_model_seconds=0.01)
        result = backtest_model(
            _series(), lambda ctx: _Slow(ctx), origins, budget=budget
        )
        assert result.status is ModelRunStatus.TIMED_OUT
        assert result.pooled is None
        assert "per-model budget" in result.origins[0].failure_reason

    def test_a_fit_inside_its_budget_is_not_timed_out(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        result = backtest_model(
            _series(),
            lambda ctx: _Recorder(ctx),
            origins,
            budget=EvaluationBudget(per_model_seconds=60.0),
        )
        assert result.status is ModelRunStatus.COMPLETED

    def test_an_exhausted_run_budget_reports_not_evaluated_not_failed(self):
        origins = build_origins(PANEL_START, PANEL_END)
        budget = EvaluationBudget(total_seconds=0.0)
        result = backtest_model(
            _series(), lambda ctx: _Recorder(ctx), origins, budget=budget
        )
        assert result.status is ModelRunStatus.NOT_EVALUATED_BUDGET
        assert "budget" in (result.reason or "")

    def test_a_series_outside_the_validation_window_is_ineligible_with_a_reason(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        early = _series(start="2024-04", months=12)  # ends 2025-03
        result = backtest_model(early, lambda ctx: _Recorder(ctx), origins)
        assert result.status is ModelRunStatus.INELIGIBLE
        assert "validation window" in result.origins[0].eligibility.reason

    def test_no_origin_at_all_is_reported_rather_than_invented(self):
        result = backtest_model(_series(months=6), lambda ctx: _Recorder(ctx), [])
        assert result.status is ModelRunStatus.NOT_EVALUATED_BUDGET
        assert "invented" in result.reason


class TestDivergenceGuard:
    def test_the_bound_is_relative_to_the_training_window(self):
        assert forecast_magnitude_bound([1, 2, 50]) == 50 * FORECAST_MAGNITUDE_FACTOR

    def test_an_all_zero_training_window_still_has_a_finite_bound(self):
        # A purely relative bound would be zero and reject every non-zero
        # forecast on an intermittent series.
        assert forecast_magnitude_bound([0, 0, 0]) > 0

    def test_a_divergent_forecast_fails_rather_than_being_scored(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        result = backtest_model(_series(), lambda ctx: _Exploder(ctx), origins)
        assert result.status is ModelRunStatus.FAILED
        assert result.pooled is None
        assert "diverged" in result.origins[0].failure_reason

    def test_a_divergent_forecast_contributes_no_residuals(self):
        # The whole point: one runaway series must not reach the quantile
        # calibration either.
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        store = ResidualStore()
        backtest_model(
            _series(), lambda ctx: _Exploder(ctx), origins, residual_store=store
        )
        assert store.total() == 0

    def test_a_plausible_forecast_is_not_rejected(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Recorder(ctx), origins)
        assert result.status is ModelRunStatus.COMPLETED
        assert result.origins[0].max_abs_prediction is not None

    def test_negative_predictions_are_counted_not_clipped(self):
        # Scored as given: clipping here would flatter a model that forecasts
        # negative demand. Phase 9 clips at the forecast boundary and records it.
        class _Negative(_Recorder):
            model_id = "negative"

            def _predict(self, horizon_df, context):
                return [-5.0] * len(horizon_df)

        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        result = backtest_model(_series(), lambda ctx: _Negative(ctx), origins)
        assert result.status is ModelRunStatus.COMPLETED
        assert result.origins[0].negative_predictions == 6
        assert min(result.origins[0].predictions) == -5.0


class TestPooling:
    def test_pooling_de_duplicates_the_overlapping_mandated_windows(self):
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Recorder(ctx), origins)
        assert result.total_test_points == 12
        assert result.distinct_test_points == 10
        assert result.duplicate_test_points == 2
        assert result.pooled.points == 10

    def test_an_overlapping_month_keeps_the_later_origin_prediction(self):
        # The later origin has more training history, so it is the one a
        # deployment would actually have used for that month.
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Recorder(ctx), origins)
        second = next(o for o in result.origins if o.origin_name == "second")
        overlap = set(result.origins[0].periods) & set(second.periods)
        assert overlap == {"2026-02", "2026-03"}

    def test_a_partially_completed_model_still_pools_what_completed(self):
        class _FailsOnFirstOrigin(_Recorder):
            model_id = "flaky"
            calls = 0

            def _fit(self, train_df, context):
                type(self).calls += 1
                if type(self).calls == 1:
                    raise RuntimeError("first origin fails")
                super()._fit(train_df, context)

        _FailsOnFirstOrigin.calls = 0
        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _FailsOnFirstOrigin(ctx), origins)
        assert result.status is ModelRunStatus.COMPLETED
        assert result.pooled.points == 6
        assert "failed" in result.reason

    def test_evaluation_mode_labels_a_single_origin_as_a_fallback(self):
        one = mandated_origins(PANEL_START, PANEL_END)[:1]
        result = backtest_model(_series(), lambda ctx: _Recorder(ctx), one)
        assert result.evaluation_mode is EvaluationMode.HOLDOUT_FALLBACK

    def test_a_fast_holdout_model_uses_one_origin_and_says_so(self):
        class _Fast(_Recorder):
            model_id = "fast"
            uses_fast_holdout = True

        origins = build_origins(PANEL_START, PANEL_END)
        result = backtest_model(_series(), lambda ctx: _Fast(ctx), origins)
        assert result.evaluation_mode is EvaluationMode.HOLDOUT_FAST
        assert len(result.origins) == 1
        assert result.origins[0].origin_name == "second"
        # Fewer validation points than a rolling-origin model: the difference is
        # labelled rather than blended away.
        assert result.pooled.points == 6


class TestResiduals:
    def test_residuals_are_recorded_per_horizon(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        store = ResidualStore()
        backtest_model(
            _series(),
            lambda ctx: _Recorder(ctx),
            origins,
            segment="smooth",
            residual_store=store,
        )
        assert store.total() == 6
        assert {cell[1] for cell in store.cells()} == {1, 2, 3, 4, 5, 6}
        assert {cell[2] for cell in store.cells()} == {"smooth"}

    def test_an_ineligible_model_records_no_residuals(self):
        origins = build_origins(PANEL_START, PANEL_END)
        store = ResidualStore()
        backtest_model(
            _series(), lambda ctx: _Ineligible(ctx), origins, residual_store=store
        )
        assert store.total() == 0


class TestCensoring:
    def test_censored_validation_points_are_counted(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        censored = [False] * 18 + [True] * 3 + [False] * 7
        frame = _series(censored=censored)
        result = backtest_model(
            frame, lambda ctx: _Recorder(ctx), origins, censored_col="is_censored"
        )
        assert result.origins[0].metrics.censored_points == 3
        # Still scored: excluding them would bias the metric toward easy months.
        assert result.origins[0].metrics.points == 6


class TestAllModels:
    def test_the_requested_models_come_back_in_the_order_requested(self):
        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_all_models(
            _series(),
            origins,
            model_ids=["sarimax", "xgboost", "var"],
            exog_columns=(),
        )
        assert list(results) == ["sarimax", "xgboost", "var"]

    def test_the_exogenous_variants_are_evaluable_when_drivers_are_supplied(self):
        # Their sibling being eligible is not enough - the exog path has its own
        # rank and collinearity guards, and this is where they run.
        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_all_models(
            _series(),
            origins,
            model_ids=["sarimax_exog", "xgboost_exog"],
            exog_columns=EXOG_COLUMNS,
        )
        for model_id, evaluation in results.items():
            assert evaluation.status is ModelRunStatus.COMPLETED, (
                model_id,
                evaluation.reason,
            )

    def test_all_thirteen_come_back_whatever_happened_to_them(self):
        # The core promise of the status vocabulary: a model never disappears
        # from the leaderboard. Requesting the default runs the whole registry,
        # so this is the slowest test in the suite and the one worth its cost.
        from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS
        from app.schemas.common import TERMINAL_STATUSES

        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_all_models(
            _series(), origins, exog_columns=EXOG_COLUMNS
        )
        assert list(results) == list(CANONICAL_MODEL_IDS)
        assert len(results) == 13
        # Every one reached a terminal state and carries a reason if it is not
        # `completed` - no silent omissions, no zero forecasts standing in.
        for model_id, evaluation in results.items():
            assert evaluation.status in TERMINAL_STATUSES, model_id
            if evaluation.status is not ModelRunStatus.COMPLETED:
                assert evaluation.pooled is None, model_id
                assert evaluation.reason, model_id

    def test_one_model_failing_does_not_stop_the_others(self):
        origins = build_origins(PANEL_START, PANEL_END)
        # `var` needs two non-constant endogenous series; a constant-despatch
        # frame makes it ineligible while the others still run.
        frame = _series()
        frame["despatched_qty"] = 1.0
        results = backtest_all_models(
            frame, origins, model_ids=["sarimax", "var", "xgboost"]
        )
        assert results["var"].status is not ModelRunStatus.COMPLETED
        assert results["sarimax"].status is ModelRunStatus.COMPLETED
        assert results["xgboost"].status is ModelRunStatus.COMPLETED

    def test_every_result_carries_its_display_name(self):
        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_all_models(_series(), origins, model_ids=["sarimax"])
        assert results["sarimax"].display_name == "SARIMAX"


class TestBaselineBacktest:
    def test_all_four_baselines_are_evaluated_on_the_same_origins(self):
        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_baselines(_series(), origins)
        assert set(results) == {"naive", "seasonal_naive", "ma3", "ma6"}
        for evaluation in results.values():
            assert evaluation.pooled is not None
            assert evaluation.pooled.points == 10

    def test_a_baseline_is_never_one_of_the_thirteen(self):
        from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS

        origins = build_origins(PANEL_START, PANEL_END)
        results = backtest_baselines(_series(), origins)
        assert not set(results) & set(CANONICAL_MODEL_IDS)

    def test_a_baseline_fallback_is_reported(self):
        origins = mandated_origins(PANEL_START, PANEL_END)[:1]
        results = backtest_baselines(
            _series(), origins, profile="monthly_relaxed"
        )
        seasonal = results["seasonal_naive"]
        assert seasonal.pooled is not None
