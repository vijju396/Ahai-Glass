"""Leakage prevention.

These are the load-bearing tests of the feature layer. A leak here does not
raise, does not fail a metric, and does not look wrong in a chart - it just
produces an accuracy figure nobody can reproduce in production.

The strongest test is `test_corrupting_the_future_changes_no_origin_feature`:
it takes a real panel, rewrites every value *after* an origin to an absurd
number, and asserts not one feature at that origin moves.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.features.feature_builder import (
    LAG_MONTHS,
    build_feature_manifest,
    build_origin_features,
    build_scoring_frame,
    build_training_frame,
)
from app.ml.features.panel import build_period_grid, index_to_period, month_index


def _panel(values: list[float], *, series: str = "AGRA|FG.X", start: str = "2024-04") -> pd.DataFrame:
    start_index = month_index(start)
    return pd.DataFrame(
        {
            "series_id": series,
            "period_index": range(start_index, start_index + len(values)),
            "target": [float(v) for v in values],
            "is_censored": [False] * len(values),
            "target_source": ["order"] * len(values),
        }
    )


def _two_series() -> pd.DataFrame:
    a = _panel([10, 0, 20, 0, 0, 30, 40, 0, 50, 60, 70, 80, 90, 100], series="A|X")
    b = _panel([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14], series="B|Y")
    return pd.concat([a, b], ignore_index=True)


class TestLagConvention:
    def test_lag_1_is_the_origin_value(self) -> None:
        """`lag_1` is what is known AT the origin - the most recent observation
        when the forecast is made. Both references define it this way
        (`lag_1 = history[-1]`)."""
        features = build_origin_features(_panel([5, 10, 20, 40]))
        assert list(features["lag_1"]) == [5.0, 10.0, 20.0, 40.0]

    def test_lag_k_steps_back_k_minus_one_months(self) -> None:
        features = build_origin_features(_panel([5, 10, 20, 40]))
        assert list(features["lag_2"]) == [pytest.approx(float("nan"), nan_ok=True), 5.0, 10.0, 20.0]
        assert features["lag_3"].tolist()[2:] == [5.0, 10.0]

    def test_early_lags_are_missing_not_zero(self) -> None:
        """A lag with no history is unknown. Filling it with zero would tell
        the model 'no demand' where the truth is 'no observation'."""
        features = build_origin_features(_panel([5, 10]))
        assert pd.isna(features["lag_12"]).all()
        assert not (features["lag_12"] == 0).any()

    def test_every_declared_lag_is_produced(self) -> None:
        features = build_origin_features(_panel(list(range(1, 20))))
        for lag in LAG_MONTHS:
            assert f"lag_{lag}" in features.columns


class TestRollingWindows:
    def test_rolling_mean_ends_at_the_origin(self) -> None:
        features = build_origin_features(_panel([3, 6, 9, 12]))
        # At the fourth origin the window [6, 9, 12] averages to 9.
        assert features["rolling_mean_3"].iloc[3] == pytest.approx(9.0)

    def test_rolling_mean_never_includes_a_future_value(self) -> None:
        features = build_origin_features(_panel([3, 6, 9, 1000]))
        # The third origin must not see the 1000 that follows it.
        assert features["rolling_mean_3"].iloc[2] == pytest.approx(6.0)

    def test_rolling_std_uses_population_ddof_zero(self) -> None:
        """Matches the references' `statistics.pstdev`, and yields 0 rather
        than NaN for a single observation."""
        features = build_origin_features(_panel([4, 4, 4, 4]))
        assert features["rolling_std_3"].iloc[3] == pytest.approx(0.0)
        assert features["rolling_std_3"].iloc[0] == pytest.approx(0.0)

    def test_partial_windows_are_computed_not_dropped(self) -> None:
        features = build_origin_features(_panel([10, 20]))
        assert features["rolling_mean_12"].iloc[1] == pytest.approx(15.0)


class TestSparsityFeatures:
    def test_nonzero_count_counts_only_nonzero_months(self) -> None:
        features = build_origin_features(_panel([5, 0, 0, 7, 0, 9]))
        assert features["nonzero_count_6"].iloc[5] == pytest.approx(3.0)

    def test_consecutive_zeros_counts_the_run_ending_at_the_origin(self) -> None:
        features = build_origin_features(_panel([5, 0, 0, 0, 4]))
        assert list(features["consecutive_zero_months"]) == [0, 1, 2, 3, 0]

    def test_a_fully_dead_series_accumulates_its_zero_run(self) -> None:
        """Trailing zeros are the obsolescence signal, so they must accumulate
        rather than reset."""
        features = build_origin_features(_panel([7, 0, 0, 0, 0, 0]))
        assert features["consecutive_zero_months"].iloc[-1] == 5

    def test_trend_is_the_three_minus_six_month_mean(self) -> None:
        features = build_origin_features(_panel([10, 10, 10, 40, 40, 40]))
        row = features.iloc[5]
        assert row["trend_3_minus_6"] == pytest.approx(
            row["rolling_mean_3"] - row["rolling_mean_6"]
        )
        assert row["trend_3_minus_6"] == pytest.approx(15.0)


class TestNoFutureInformation:
    def test_corrupting_the_future_changes_no_origin_feature(self) -> None:
        """The decisive test. Rewrite everything after an origin to an absurd
        value and assert not one feature at that origin moves."""
        clean = _panel(list(range(1, 25)))
        origin_position = 11

        baseline = build_origin_features(clean)
        corrupted_panel = clean.copy()
        corrupted_panel.loc[origin_position + 1 :, "target"] = 1e9
        corrupted_panel.loc[origin_position + 1 :, "is_censored"] = True
        corrupted = build_origin_features(corrupted_panel)

        feature_columns = [
            column
            for column in baseline.columns
            if column not in {"series_id", "period_index"}
        ]
        before = baseline.iloc[: origin_position + 1][feature_columns]
        after = corrupted.iloc[: origin_position + 1][feature_columns]
        pd.testing.assert_frame_equal(before, after, check_dtype=False)

    def test_one_series_cannot_see_another(self) -> None:
        """Grouping must isolate series; a bare shift over a concatenated frame
        would bleed the tail of one series into the head of the next."""
        panel = _two_series()
        features = build_origin_features(panel)
        first_b = features[features["series_id"] == "B|Y"].iloc[0]
        assert pd.isna(first_b["lag_2"])
        assert first_b["lag_1"] == pytest.approx(1.0)
        assert first_b["consecutive_zero_months"] == 0

    def test_row_order_does_not_change_the_features(self) -> None:
        panel = _two_series()
        ordered = build_origin_features(panel)
        shuffled = build_origin_features(
            panel.sample(frac=1.0, random_state=42).reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(
            ordered.sort_values(["series_id", "period_index"]).reset_index(drop=True),
            shuffled.sort_values(["series_id", "period_index"]).reset_index(drop=True),
            check_dtype=False,
        )

    def test_a_gapped_panel_is_rejected_rather_than_silently_wrong(self) -> None:
        """`shift` counts rows, so a missing month would make `lag_2` mean 'two
        observations back'. That must raise, not quietly mislabel."""
        panel = _panel([1, 2, 3, 4])
        gapped = panel.drop(index=2).reset_index(drop=True)
        with pytest.raises(ValueError, match="period gaps"):
            build_origin_features(gapped)


class TestTrainingFrame:
    def test_the_target_is_the_origin_plus_horizon(self) -> None:
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1, 3, 6))
        for _, row in frame.iterrows():
            assert row["target_period"] == row["origin_period"] + row["horizon"]

    def test_y_matches_the_panel_value_at_the_target_period(self) -> None:
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1, 6))
        lookup = dict(zip(panel["period_index"], panel["target"], strict=True))
        for _, row in frame.iterrows():
            assert row["y"] == pytest.approx(lookup[row["target_period"]])

    def test_no_feature_equals_the_value_being_predicted(self) -> None:
        """A direct test of the leak that matters: with distinct values, no lag
        or rolling feature may coincide with y."""
        panel = _panel([float(v) for v in range(100, 124)])
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1, 2, 3, 4, 5, 6))
        lag_columns = [f"lag_{lag}" for lag in LAG_MONTHS]
        for _, row in frame.iterrows():
            for column in lag_columns:
                if pd.notna(row[column]):
                    assert row[column] != row["y"]

    def test_the_training_cut_bounds_the_target_not_only_the_origin(self) -> None:
        """Filtering only the origin would let a horizon-6 row read a target
        six months past the cut - chronological-looking, still a leak."""
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        cut = month_index("2025-03")
        frame = build_training_frame(
            panel, features, horizons=(1, 6), max_origin_period=cut
        )
        assert frame["origin_period"].max() <= cut
        assert frame["target_period"].max() <= cut

    def test_all_horizons_share_one_frame(self) -> None:
        """Horizon is a feature, so one fitted model answers every horizon."""
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1, 2, 3, 4, 5, 6))
        assert sorted(frame["horizon"].unique()) == [1, 2, 3, 4, 5, 6]
        assert "horizon" in frame.columns

    def test_calendar_month_describes_the_target_period(self) -> None:
        panel = _panel(list(range(1, 25)), start="2024-04")
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1,))
        row = frame.iloc[0]
        expected = int(index_to_period(int(row["target_period"])).split("-")[1])
        assert row["calendar_month"] == expected

    def test_same_month_last_year_is_relative_to_the_target(self) -> None:
        panel = _panel(list(range(1, 30)))
        features = build_origin_features(panel)
        frame = build_training_frame(panel, features, horizons=(1,))
        lookup = dict(zip(panel["period_index"], panel["target"], strict=True))
        row = frame[frame["target_period"] - 12 >= panel["period_index"].min()].iloc[0]
        assert row["same_month_last_year"] == pytest.approx(
            lookup[row["target_period"] - 12]
        )

    def test_static_attributes_are_attached(self) -> None:
        panel = _panel(list(range(1, 25)))
        panel["region"] = "NORTH-1"
        features = build_origin_features(panel)
        frame = build_training_frame(
            panel, features, horizons=(1,), static_columns=("region",)
        )
        assert (frame["region"] == "NORTH-1").all()

    def test_an_empty_panel_yields_an_empty_frame(self) -> None:
        empty = _panel([]).iloc[0:0]
        assert build_training_frame(empty, empty).empty


class TestScoringFrame:
    def test_it_produces_one_row_per_series_and_horizon(self) -> None:
        panel = _two_series()
        features = build_origin_features(panel)
        origin = int(panel["period_index"].max())
        frame = build_scoring_frame(
            panel, features, origin_period=origin, horizons=(1, 2, 3, 4, 5, 6)
        )
        assert len(frame) == 2 * 6

    def test_it_carries_no_target(self) -> None:
        """Those periods have not happened, so a `y` would be fabricated."""
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        frame = build_scoring_frame(
            panel, features, origin_period=int(panel["period_index"].max())
        )
        assert "y" not in frame.columns

    def test_target_periods_are_strictly_after_the_origin(self) -> None:
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        origin = int(panel["period_index"].max())
        frame = build_scoring_frame(panel, features, origin_period=origin)
        assert (frame["target_period"] > origin).all()

    def test_an_unknown_origin_yields_nothing_rather_than_guessing(self) -> None:
        panel = _panel(list(range(1, 25)))
        features = build_origin_features(panel)
        assert build_scoring_frame(panel, features, origin_period=999_999).empty


class TestPeriodGrid:
    def test_it_materialises_the_missing_months(self) -> None:
        observations = pd.DataFrame(
            {
                "series_id": ["A|X", "A|X"],
                "period_index": [month_index("2025-01"), month_index("2025-04")],
            }
        )
        grid, stats = build_period_grid(observations, panel_end=month_index("2025-04"))
        assert len(grid) == 4
        assert stats.observed_rows == 2
        assert stats.materialised_zero_rows == 2

    def test_a_series_gets_no_invented_history_before_its_first_month(self) -> None:
        """A SKU first listed in 2026 must not acquire two years of zeros."""
        observations = pd.DataFrame(
            {
                "series_id": ["A|X", "B|Y"],
                "period_index": [month_index("2024-04"), month_index("2026-06")],
            }
        )
        grid, _ = build_period_grid(observations, panel_end=month_index("2026-07"))
        b_rows = grid[grid["series_id"] == "B|Y"]
        assert b_rows["period_index"].min() == month_index("2026-06")
        assert len(b_rows) == 2

    def test_panel_start_policy_aligns_every_series(self) -> None:
        observations = pd.DataFrame(
            {
                "series_id": ["A|X", "B|Y"],
                "period_index": [month_index("2024-04"), month_index("2026-06")],
            }
        )
        grid, _ = build_period_grid(
            observations, panel_end=month_index("2026-07"), start_policy="panel_start"
        )
        assert grid.groupby("series_id")["period_index"].min().nunique() == 1

    def test_an_unknown_policy_is_rejected(self) -> None:
        observations = pd.DataFrame(
            {"series_id": ["A|X"], "period_index": [month_index("2024-04")]}
        )
        with pytest.raises(ValueError, match="start_policy"):
            build_period_grid(observations, panel_end=1, start_policy="nonsense")

    def test_the_grid_is_gapless_so_features_can_use_it(self) -> None:
        observations = pd.DataFrame(
            {
                "series_id": ["A|X"] * 3,
                "period_index": [
                    month_index("2024-04"), month_index("2024-09"), month_index("2025-02")
                ],
            }
        )
        grid, _ = build_period_grid(observations, panel_end=month_index("2025-02"))
        steps = grid.sort_values("period_index")["period_index"].diff().dropna()
        assert (steps == 1).all()


class TestMonthIndex:
    def test_it_round_trips(self) -> None:
        for period in ("2024-01", "2024-04", "2025-12", "2026-07"):
            assert index_to_period(month_index(period)) == period

    def test_consecutive_months_differ_by_one(self) -> None:
        assert month_index("2025-01") - month_index("2024-12") == 1

    def test_a_year_is_twelve(self) -> None:
        assert month_index("2026-04") - month_index("2025-04") == 12


class TestFeatureManifest:
    def test_every_feature_declares_whether_it_uses_target_history(self) -> None:
        manifest = build_feature_manifest(static_columns=("region",))
        for spec in manifest.specs:
            assert isinstance(spec.uses_target_history, bool)
            assert spec.definition

    def test_calendar_and_horizon_do_not_use_target_history(self) -> None:
        """These are the genuinely future-known features."""
        manifest = build_feature_manifest()
        by_name = {spec.name: spec for spec in manifest.specs}
        assert by_name["calendar_month"].uses_target_history is False
        assert by_name["horizon"].uses_target_history is False
        assert by_name["lag_1"].uses_target_history is True

    def test_static_attributes_are_future_known(self) -> None:
        manifest = build_feature_manifest(static_columns=("region", "glass_type"))
        by_name = {spec.name: spec for spec in manifest.specs}
        assert by_name["region"].uses_target_history is False
        assert by_name["glass_type"].kind == "static_attribute"

    def test_the_manifest_reports_its_deepest_lookback(self) -> None:
        manifest = build_feature_manifest()
        assert manifest.max_lookback_months == 11

    def test_it_serialises_the_lag_convention(self) -> None:
        payload = build_feature_manifest().as_dict()
        assert "lag_1 is the value AT the forecast origin" in payload["lag_convention"]
        assert payload["feature_count"] == len(payload["features"])
