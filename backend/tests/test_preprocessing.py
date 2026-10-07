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

    def test_mean_mrp_is_weighted_by_quantity(self) -> None:
        """So `ordered_qty * mean_mrp` reproduces the sum of the lines (D-139).

        An unweighted mean of the rates made the network order value read
        Rs 860.04Cr against Rs 857.12Cr in the client's own file, because
        19,359 cells hold more than one price and the cheaper lines carried
        more units.
        """
        # 10 units at 100 and 90 units at 200 -> 19,000 over 100 units.
        row = MonthlyFactRow(
            "AGRA", "FG.X", "2025-04",
            ordered_qty=100.0, mrp_value_sum=10 * 100.0 + 90 * 200.0, mrp_qty_sum=100.0,
        )
        assert row.mean_mrp == 190.0
        assert row.ordered_qty * row.mean_mrp == 19_000.0

    def test_an_unweighted_mean_would_have_got_it_wrong(self) -> None:
        """The plain average of 100 and 200 is 150, and 100 x 150 is 15,000 -
        3,999 short of the 19,000 the lines actually add to."""
        row = MonthlyFactRow(
            "AGRA", "FG.X", "2025-04",
            ordered_qty=100.0, mrp_value_sum=10 * 100.0 + 90 * 200.0, mrp_qty_sum=100.0,
        )
        assert row.mean_mrp != 150.0

    def test_a_blank_despatch_is_unknown_not_zero(self) -> None:
        """44 real lines have no despatch quantity (D-139).

        Counting them as nothing despatched turned their whole ordered
        quantity into shortfall - 246 units that were never measured as short.
        """
        row = MonthlyFactRow(
            "AGRA", "FG.X", "2025-04", ordered_qty=10.0, despatch_unknown_lines=1,
        )
        assert row.shortfall_qty == 0.0
        assert row.is_censored is False
        assert row.despatch_unknown_lines == 1
