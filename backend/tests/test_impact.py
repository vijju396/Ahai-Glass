"""The impact report keeps measurement and assumption apart.

These tests are mostly about what the module refuses to do. The arithmetic is
trivial; the risk is that a projected figure acquires the authority of a
measured one, or that a horizon with no evidence silently borrows a
neighbour's number.
"""

from __future__ import annotations

import pytest

from app.domain.ais.impact import (
    DEFAULT_ASSUMPTIONS,
    MIN_POINTS_PER_HORIZON,
    Exposure,
    ImpactReport,
    build_caveats,
    horizon_accuracy,
    project,
    set_monthly_basis,
)
from app.services.impact_service import _folds


def _exposure(**kw):
    base = dict(
        ordered_units=72158.0,
        unfilled_units=7202.0,
        unfilled_rows=289,
        demand_value=247_200_000.0,
        fill_rate_pct=85.1,
        series_count=40,
    )
    base.update(kw)
    return Exposure(**base)


def _fold(horizons, actuals, predictions):
    return (horizons, actuals, predictions)


class TestHorizonAccuracy:
    def test_error_is_pooled_by_volume_not_averaged_over_series(self):
        """A tiny series with a huge percentage error must not outvote a large one.

        One unit mispredicted by one unit is a 100% error; a thousand units
        mispredicted by ten is 1%. Averaging the percentages says 50%, which
        describes neither. Pooling absolute error over pooled volume says
        about 1.1%, which is what a planner stocking those units experiences.
        """
        champion = [_fold([1], [1.0], [2.0]), _fold([1], [1000.0], [990.0])]
        rows = horizon_accuracy(champion, [])
        assert rows[0].champion_wape == pytest.approx(100 * 11 / 1001, abs=0.01)

    def test_a_horizon_where_the_baseline_wins_reports_a_negative_reduction(self):
        champion = [_fold([5], [100.0], [70.0])]
        baseline = [_fold([5], [100.0], [90.0])]
        rows = horizon_accuracy(champion, baseline)
        assert rows[0].reduction_pct is not None
        assert rows[0].reduction_pct < 0

    def test_non_numeric_points_are_dropped_not_counted_as_zero(self):
        champion = [_fold([1, 1], [100.0, None], [90.0, 50.0])]
        rows = horizon_accuracy(champion, [])
        assert rows[0].points == 1
        assert rows[0].champion_wape == pytest.approx(10.0)

    def test_a_zero_volume_horizon_yields_none_not_a_division_error(self):
        rows = horizon_accuracy([_fold([1], [0.0], [0.0])], [])
        assert rows[0].champion_wape is None


class TestProjection:
    def test_a_horizon_with_no_measured_reduction_projects_nothing(self):
        exposure = _exposure()
        out = project([], exposure, DEFAULT_ASSUMPTIONS, history_months=28, horizons=[1])
        assert out[0].recovered_revenue == 0.0
        assert out[0].measured is False

    def test_a_negative_reduction_projects_nothing_rather_than_a_loss(self):
        """A horizon the baseline wins earns no benefit - and no penalty either.

        Projecting a negative rupee figure would imply the system destroys
        value there, which the measurement does not support: it supports
        "no improvement to claim".
        """
        rows = horizon_accuracy(
            [_fold([1] * 20, [100.0] * 20, [60.0] * 20)],
            [_fold([1] * 20, [100.0] * 20, [90.0] * 20)],
        )
        out = project(rows, _exposure(), DEFAULT_ASSUMPTIONS, history_months=28, horizons=[1])
        assert rows[0].reduction_pct < 0
        assert out[0].recovered_revenue == 0.0

    def test_a_thin_horizon_is_not_reported_even_with_a_positive_reduction(self):
        thin = horizon_accuracy(
            [_fold([1], [100.0], [95.0])],
            [_fold([1], [100.0], [80.0])],
        )
        assert thin[0].points < MIN_POINTS_PER_HORIZON
        out = project(thin, _exposure(), DEFAULT_ASSUMPTIONS, history_months=28, horizons=[1])
        assert out[0].measured is False
        assert out[0].recovered_revenue == 0.0

    def test_revenue_scales_linearly_with_the_recovery_assumption(self):
        rows = horizon_accuracy(
            [_fold([1] * 20, [100.0] * 20, [90.0] * 20)],
            [_fold([1] * 20, [100.0] * 20, [80.0] * 20)],
        )
        exposure = _exposure()
        low = project(rows, exposure, {**DEFAULT_ASSUMPTIONS, "recovery_share": 0.3},
                      history_months=28, horizons=[1])[0]
        high = project(rows, exposure, {**DEFAULT_ASSUMPTIONS, "recovery_share": 0.6},
                       history_months=28, horizons=[1])[0]
        assert high.recovered_revenue == pytest.approx(low.recovered_revenue * 2)

    def test_the_window_scales_with_the_horizon(self):
        exposure = _exposure(unfilled_units=280.0)
        assert set_monthly_basis(exposure, 28) == pytest.approx(10.0)
        out = project([], exposure, DEFAULT_ASSUMPTIONS, history_months=28, horizons=[1, 3, 6])
        assert [p.unfilled_units_in_window for p in out] == pytest.approx([10.0, 30.0, 60.0])

    def test_zero_history_months_does_not_divide_by_zero(self):
        assert set_monthly_basis(_exposure(), 0) == 0.0


class TestCaveats:
    def test_the_three_structural_limits_are_always_present(self):
        text = " ".join(build_caveats(ImpactReport()))
        assert "No forecast month has elapsed" in text
        assert "inventory-policy backtest" in text
        assert "counterfactual" in text

    def test_a_losing_horizon_is_named_in_the_caveats(self):
        report = ImpactReport(
            horizons=horizon_accuracy(
                [_fold([5] * 20, [100.0] * 20, [60.0] * 20)],
                [_fold([5] * 20, [100.0] * 20, [90.0] * 20)],
            )
        )
        assert any("month 5" in c for c in build_caveats(report))

    def test_series_beaten_by_a_baseline_are_reported(self):
        report = ImpactReport(series_count=40, beaten_by_baseline=16)
        assert any("16 of 40" in c for c in build_caveats(report))


class TestFoldParsing:
    def test_an_already_parsed_list_is_accepted(self):
        """`origins_json` is a JSON column, so SQLAlchemy returns a list.

        An earlier version assumed a string and `json.loads` raised into the
        `except`, returning no folds at all - every series paired to nothing
        and the panel reported no measured horizons. The regression is worth a
        test because the failure was silent.
        """
        parsed = [{"horizons": [1], "actuals": [1.0], "predictions": [2.0]}]
        assert len(_folds(parsed)) == 1

    def test_a_json_string_is_still_accepted(self):
        import json

        raw = json.dumps([{"horizons": [1], "actuals": [1.0], "predictions": [2.0]}])
        assert len(_folds(raw)) == 1

    def test_malformed_input_yields_no_folds_rather_than_raising(self):
        assert _folds("not json") == []
        assert _folds(None) == []
        assert _folds({"not": "a list"}) == []

    def test_a_fold_missing_predictions_is_skipped(self):
        assert _folds([{"horizons": [1], "actuals": [1.0]}]) == []
