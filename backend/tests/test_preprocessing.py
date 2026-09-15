"""Preprocessing shape and semantics.

The full run streams 2.6 M rows and takes ~6 minutes, so it is exercised
end to end separately (docs/STATUS.md). These tests cover the units where a
mistake would be invisible in the aggregate numbers.
"""

from __future__ import annotations

from datetime import date

from app.services.preprocessing.ais_preprocessing import MonthlyFactRow, month_key


class TestMonthKey:
    def test_pads_the_month(self) -> None:
        assert month_key(date(2025, 4, 1)) == "2025-04"
        assert month_key(date(2026, 12, 31)) == "2026-12"

    def test_every_day_of_a_month_maps_to_one_key(self) -> None:
        keys = {month_key(date(2025, 4, day)) for day in (1, 15, 30)}
        assert keys == {"2025-04"}


class TestMonthlyFactRow:
    def test_censoring_is_set_only_when_demand_went_short(self) -> None:
        served = MonthlyFactRow("AGRA", "FG.X", "2025-04", ordered_qty=10, despatched_qty=10)
        assert served.is_censored is False
        short = MonthlyFactRow("AGRA", "FG.X", "2025-04", ordered_qty=10, shortfall_qty=3)
        assert short.is_censored is True

    def test_over_delivery_does_not_count_as_censoring(self) -> None:
        """Shipping more than was ordered says nothing about unmet demand."""
        row = MonthlyFactRow(
            "AGRA", "FG.X", "2025-04", ordered_qty=10, despatched_qty=13,
            over_delivered_qty=3,
        )
        assert row.is_censored is False

    def test_mean_mrp_is_none_rather_than_zero_without_observations(self) -> None:
        row = MonthlyFactRow("AGRA", "FG.X", "2025-04")
        assert row.mean_mrp is None

    def test_mean_mrp_averages_the_observed_prices(self) -> None:
        row = MonthlyFactRow("AGRA", "FG.X", "2025-04", mrp_sum=900.0, mrp_count=3)
        assert row.mean_mrp == 300.0
