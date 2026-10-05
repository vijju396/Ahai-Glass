"""The full-network analytics frame: the target rule, the joins, what it is not.

Overall Analysis reports the client's whole network while every other page
stays on the workspace (D-138). The frame that serves it is assembled from the
preprocessed facts rather than the panel, because an unrestricted panel build
exhausts memory. These tests pin the three things that could silently go wrong
in that substitution: the target rule drifting from the panel's, a dimension
join dropping rows, and the coverage counts overstating what is covered.
"""

from __future__ import annotations

import pandas as pd

from app.domain.ais import network_frame


def _orders(rows: list[dict]) -> pd.DataFrame:
    base = {
        "canonical_branch": "BENGALURU", "canonical_sku": "FG.A", "period": "2025-W14",
        "ordered_qty": 100.0, "despatched_qty": 90.0, "shortfall_qty": 10.0,
        "over_delivered_qty": 0.0, "is_censored": True, "line_count": 1, "mean_mrp": 50.0,
    }
    return pd.DataFrame([base | r for r in rows]) if rows else pd.DataFrame(columns=list(base))


def _sales(rows: list[dict]) -> pd.DataFrame:
    base = {
        "canonical_branch": "BENGALURU", "canonical_sku": "FG.A", "period": "2024-W20",
        "invoiced_qty": 70.0, "line_count": 1, "mean_mrp": 50.0,
    }
    return pd.DataFrame([base | r for r in rows]) if rows else pd.DataFrame(columns=list(base))


def _product(skus: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {"canonical_sku": s, "glass_type": "Lam", "product_group": "G", "value_class": "A",
         "vehicle_category": "PV", "vehicle_age_category": "New", "oem_status": "OEM",
         "is_non_glass": False, "in_product_master": True, "has_substitute": False,
         "substitute_sku_1": None}
        for s in skus
    ])


def _branch(branches: list[str]) -> pd.DataFrame:
    return pd.DataFrame([
        {"canonical_branch": b, "branch_name": b.title(), "region": "SOUTH", "zone": "Z1",
         "supply_hub": "H", "tier": "T1", "in_location_master": True,
         "avg_lead_time_days": 4.0, "std_lead_time_days": 1.0, "truck_moq": 7.8}
        for b in branches
    ])


def _build(orders, sales, skus=("FG.A",), branches=("BENGALURU",)):
    return network_frame.build(
        orders, sales, _product(list(skus)), _branch(list(branches)), grain="weekly"
    )


class TestTargetRule:
    """The panel's rule, not a second one (D-002)."""

    def test_an_order_row_is_the_target_and_is_labelled_order(self) -> None:
        frame, _ = _build(_orders([{}]), _sales([]))
        row = frame.iloc[0]
        assert row["target"] == 100.0
        assert row["target_source"] == "order"

    def test_sales_before_the_order_window_become_the_proxy(self) -> None:
        frame, cov = _build(_orders([{"period": "2025-W14"}]), _sales([{"period": "2024-W20"}]))
        assert cov["target_source_rows"] == {"order": 1, "sales_proxy": 1}
        proxy = frame.loc[frame["target_source"] == "sales_proxy"].iloc[0]
        assert proxy["target"] == 70.0

    def test_sales_inside_the_order_window_are_dropped_not_merged(self) -> None:
        """A period filter, not a row preference.

        Inside the order window a series with no order row has genuinely zero
        ordered demand, and invoiced sales must not overwrite that.
        """
        frame, cov = _build(
            _orders([{"period": "2025-W14"}]),
            _sales([{"period": "2025-W20", "canonical_sku": "FG.A"}]),
        )
        assert cov["target_source_rows"] == {"order": 1}
        assert len(frame) == 1

    def test_a_proxy_row_carries_null_despatch_and_null_censoring(self) -> None:
        """An invoice says what was sold and nothing about what was asked for."""
        frame, _ = _build(_orders([{"period": "2025-W14"}]), _sales([{"period": "2024-W20"}]))
        proxy = frame.loc[frame["target_source"] == "sales_proxy"].iloc[0]
        assert pd.isna(proxy["despatched_qty"])
        assert pd.isna(proxy["shortfall_qty"])
        assert pd.isna(proxy["is_censored"])


class TestDimensions:
    def test_product_and_branch_attributes_are_joined(self) -> None:
        frame, _ = _build(_orders([{}]), _sales([]))
        row = frame.iloc[0]
        assert row["glass_type"] == "Lam"
        assert row["value_class"] == "A"
        assert row["region"] == "SOUTH"

    def test_a_sku_absent_from_the_master_keeps_its_row(self) -> None:
        """Dropping it would quietly lose demand from every total."""
        frame, _ = _build(
            _orders([{"canonical_sku": "FG.UNKNOWN"}]), _sales([]), skus=["FG.A"]
        )
        assert len(frame) == 1
        assert pd.isna(frame.iloc[0]["glass_type"])


class TestDerivedColumns:
    def test_it_derives_the_same_value_columns_the_panel_path_does(self) -> None:
        """Shared with `analytics.derive_columns`, never reimplemented here."""
        frame, _ = _build(_orders([{}]), _sales([]))
        row = frame.iloc[0]
        assert row["demand_value"] == 100.0 * 50.0
        assert row["despatch_value"] == 90.0 * 50.0
        assert row["shortfall_positive"] == 10.0

    def test_period_stays_comparable(self) -> None:
        """Categorical `period` broke min/max in the shared analytics code."""
        frame, _ = _build(_orders([{"period": "2025-W14"}, {"period": "2025-W20"}]), _sales([]))
        assert frame["period"].min() == "2025-W14"
        assert frame["period"].max() == "2025-W20"


class TestCoverage:
    def test_counts_are_taken_on_the_order_book(self) -> None:
        """The scope denominator counts the order book.

        Counting proxy-only SKUs in the numerator made the banner read
        "2,315 of 2,063" - a numerator larger than its own denominator.
        """
        frame, cov = _build(
            _orders([{"canonical_sku": "FG.A"}]),
            _sales([{"canonical_sku": "FG.PROXYONLY", "period": "2024-W20"}]),
            skus=["FG.A", "FG.PROXYONLY"],
        )
        assert cov["skus"] == 1
        assert cov["skus_including_proxy_only"] == 2

    def test_it_states_that_it_holds_observed_rows_only(self) -> None:
        """No materialised grid, so row counts are not panel row counts."""
        _frame, cov = _build(_orders([{}]), _sales([]))
        assert cov["observed_rows_only"] is True
        assert "not from the modelling panel" in cov["note"]

    def test_the_period_range_is_reported_chronologically(self) -> None:
        frame, cov = _build(
            _orders([{"period": "2025-W20"}, {"period": "2025-W14"}]), _sales([])
        )
        assert cov["period_range"] == ["2025-W14", "2025-W20"]
        assert cov["periods"] == 2
