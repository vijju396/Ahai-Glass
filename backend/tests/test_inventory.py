"""Inventory recommendation arithmetic and honesty.

The arithmetic is pure, so it is asserted exactly against the policy in
`docs/AIS_DOMAIN_RULES.md` §4. The honesty properties are asserted just as
hard, because they are the ones that decide whether a planner can act on a
number:

- a missing forecast, stock record or lead time produces a **stated reason and
  no number**, never a zero,
- a long position recommends zero and names the surplus, never a negative order,
- the monthly-to-protection-period scaling caveat appears whenever it applies,
- the single-snapshot limitation is on every row,
- MOQ and case-pack rounding are applied only where the source has them, and
  the pre-rounding requirement stays visible.
"""

from __future__ import annotations

import pytest

from app.domain.ais.inventory import (
    DAYS_PER_MONTH,
    SCALING_CAVEAT,
    SNAPSHOT_CAVEAT,
    InventoryInputs,
    days_of_cover,
    recommend,
)


def _inputs(**kwargs) -> InventoryInputs:
    base = {
        "scope_key": "JAIPUR|SKU1",
        "canonical_branch": "JAIPUR",
        "canonical_sku": "SKU1",
        "monthly_quantile_forecast": 100.0,
        "monthly_point_forecast": 80.0,
        "service_level": 95,
        "review_period_days": 30,
        "lead_time_days": 3.0,
        "usable_stock_on_hand": 40.0,
    }
    base.update(kwargs)
    return InventoryInputs(**base)


class TestTheCalculation:
    def test_the_protection_period_is_review_plus_lead_time(self) -> None:
        result = recommend(_inputs())
        assert result.protection_period_days == 33.0
        assert result.protection_months == pytest.approx(33.0 / DAYS_PER_MONTH)

    def test_the_order_up_to_level_scales_the_quantile_forecast(self) -> None:
        result = recommend(_inputs())
        assert result.order_up_to_level == pytest.approx(
            100.0 * 33.0 / DAYS_PER_MONTH
        )

    def test_the_recommended_order_nets_off_stock_and_adds_backorders(self) -> None:
        result = recommend(
            _inputs(
                usable_stock_on_hand=40.0,
                confirmed_stock_on_order=10.0,
                backorders=5.0,
            )
        )
        assert result.recommended_order == pytest.approx(
            result.order_up_to_level - 40.0 - 10.0 + 5.0
        )

    def test_the_service_level_selects_the_quantile_that_was_passed(self) -> None:
        low = recommend(_inputs(monthly_quantile_forecast=90.0, service_level=80))
        high = recommend(_inputs(monthly_quantile_forecast=130.0, service_level=95))
        assert high.order_up_to_level > low.order_up_to_level
        assert low.inputs.service_level == 80
        assert high.inputs.service_level == 95

    def test_days_of_cover_uses_the_point_forecast_not_the_quantile(self) -> None:
        """Cover is what the stock actually lasts at expected demand; using a
        q95 would understate it."""
        result = recommend(_inputs(usable_stock_on_hand=80.0))
        assert result.days_of_cover == pytest.approx(80.0 / 80.0 * DAYS_PER_MONTH)

    def test_a_longer_lead_time_raises_the_order(self) -> None:
        short = recommend(_inputs(lead_time_days=3.0))
        long = recommend(_inputs(lead_time_days=21.0))
        assert long.recommended_order > short.recommended_order
        assert long.protection_period_days == 51.0

    def test_every_input_is_returned_beside_the_answer(self) -> None:
        payload = recommend(_inputs()).as_dict()
        for key in (
            "order_up_to_level",
            "usable_stock_on_hand",
            "confirmed_stock_on_order",
            "backorders",
            "lead_time_days",
            "review_period_days",
            "protection_period_days",
            "service_level",
            "recommended_order",
        ):
            assert key in payload, key
            assert payload[key] is not None, key


class TestRefusalsRatherThanGuesses:
    def test_no_forecast_gives_a_reason_and_no_number(self) -> None:
        result = recommend(_inputs(monthly_quantile_forecast=None))
        assert result.recommended_order is None
        assert result.order_up_to_level is None
        assert "no demand figure" in result.unavailable_reason
        assert "Nothing was substituted" in result.unavailable_reason

    def test_no_stock_record_is_refused_rather_than_treated_as_zero(self) -> None:
        """Absent stock treated as zero would order a full replenishment for an
        item that may be fully stocked."""
        result = recommend(_inputs(usable_stock_on_hand=None))
        assert result.recommended_order is None
        assert "No stock record" in result.unavailable_reason
        assert "may be fully stocked" in result.unavailable_reason

    def test_no_lead_time_and_no_default_is_refused(self) -> None:
        result = recommend(_inputs(lead_time_days=None))
        assert result.recommended_order is None
        assert "lead time" in result.unavailable_reason

    def test_a_defaulted_lead_time_is_used_but_flagged(self) -> None:
        result = recommend(_inputs(lead_time_days=None), default_lead_time_days=3.0)
        assert result.recommended_order is not None
        assert any("network default" in warning for warning in result.warnings)

    def test_a_refused_row_never_reports_zero_to_order(self) -> None:
        """Zero means 'order nothing'; the two must not be confused."""
        for kwargs in (
            {"monthly_quantile_forecast": None},
            {"usable_stock_on_hand": None},
            {"lead_time_days": None},
        ):
            result = recommend(_inputs(**kwargs))
            assert result.recommended_order is None
            assert result.unavailable_reason


class TestLongPositions:
    def test_ample_stock_recommends_zero_and_names_the_surplus(self) -> None:
        result = recommend(_inputs(usable_stock_on_hand=500.0))
        assert result.recommended_order == 0.0
        assert result.raw_recommended_order < 0
        assert any("already cover" in warning for warning in result.warnings)

    def test_it_never_returns_a_negative_order(self) -> None:
        result = recommend(_inputs(usable_stock_on_hand=10_000.0))
        assert result.recommended_order >= 0.0

    def test_the_raw_requirement_stays_visible(self) -> None:
        result = recommend(_inputs(usable_stock_on_hand=500.0))
        assert result.raw_recommended_order is not None
        assert result.raw_recommended_order != result.recommended_order


class TestRoundingRules:
    def test_an_moq_raises_a_small_order_and_says_so(self) -> None:
        result = recommend(_inputs(usable_stock_on_hand=100.0, moq=50.0))
        assert result.recommended_order == 50.0
        assert any("below the MOQ" in warning for warning in result.warnings)

    def test_a_case_pack_rounds_up_to_whole_packs(self) -> None:
        result = recommend(_inputs(usable_stock_on_hand=40.0, case_pack=25.0))
        assert result.recommended_order % 25.0 == 0
        assert result.recommended_order >= result.raw_recommended_order
        assert any("case pack" in warning for warning in result.warnings)

    def test_a_truck_quantity_advises_but_does_not_inflate_the_order(self) -> None:
        """Ordering stock that is not needed is not a freight saving."""
        result = recommend(_inputs(usable_stock_on_hand=40.0, truck_quantity=10_000.0))
        assert result.recommended_order < 10_000.0
        assert any("truck quantity" in warning for warning in result.warnings)

    def test_rounding_can_be_switched_off_to_see_the_raw_requirement(self) -> None:
        result = recommend(
            _inputs(usable_stock_on_hand=100.0, moq=50.0), apply_moq=False
        )
        assert result.recommended_order == pytest.approx(result.raw_recommended_order)

    def test_no_moq_in_the_source_means_no_rounding_at_all(self) -> None:
        """`Replenishment A/B/C` are zero for all 57 branches and are never
        used as an MOQ."""
        result = recommend(_inputs(moq=None, case_pack=None))
        assert result.recommended_order == pytest.approx(result.raw_recommended_order)


class TestCaveatsAndWarnings:
    def test_the_snapshot_limitation_is_on_every_row(self) -> None:
        for kwargs in ({}, {"monthly_quantile_forecast": None}):
            result = recommend(_inputs(**kwargs))
            assert SNAPSHOT_CAVEAT in result.caveats
            assert result.as_dict()["is_current_snapshot_estimate"] is True

    def test_the_scaling_caveat_appears_when_the_period_exceeds_a_month(
        self,
    ) -> None:
        result = recommend(_inputs(lead_time_days=3.0))
        assert result.protection_months > 1.0
        assert SCALING_CAVEAT in result.caveats

    def test_it_does_not_appear_when_the_period_is_under_a_month(self) -> None:
        result = recommend(_inputs(review_period_days=7, lead_time_days=3.0))
        assert result.protection_months < 1.0
        assert SCALING_CAVEAT not in result.caveats

    def test_a_negative_stock_row_is_surfaced_not_clamped_away(self) -> None:
        result = recommend(_inputs(negative_stock_rows=2))
        assert any("negative stock row" in warning for warning in result.warnings)
        assert any("not a clamped zero" in warning for warning in result.warnings)

    def test_censored_history_raises_the_may_be_higher_warning(self) -> None:
        result = recommend(_inputs(is_censored=True))
        assert any("censored" in warning for warning in result.warnings)

    def test_a_sales_proxy_forecast_is_labelled_not_equated(self) -> None:
        result = recommend(_inputs(target_source="sales_proxy"))
        assert any("sales_proxy" in warning for warning in result.warnings)
        assert any("substitute" in warning for warning in result.warnings)

    def test_an_order_sourced_forecast_carries_no_proxy_warning(self) -> None:
        result = recommend(_inputs(target_source="order"))
        assert not any("sales_proxy" in warning for warning in result.warnings)

    def test_substitutes_are_named_but_not_netted_off(self) -> None:
        result = recommend(_inputs(substitute_skus=["SKU2", "SKU3"]))
        warning = next(w for w in result.warnings if "Substitutes exist" in w)
        assert "SKU2" in warning
        assert "not netted off" in warning


class TestDaysOfCover:
    def test_it_converts_stock_into_days_at_monthly_demand(self) -> None:
        assert days_of_cover(100.0, 100.0) == pytest.approx(DAYS_PER_MONTH)
        assert days_of_cover(50.0, 100.0) == pytest.approx(DAYS_PER_MONTH / 2)

    def test_zero_demand_gives_none_rather_than_infinity(self) -> None:
        """Stock with no demand is a placement problem, not infinite cover."""
        assert days_of_cover(100.0, 0.0) is None
        assert days_of_cover(100.0, None) is None
        assert days_of_cover(None, 100.0) is None

    def test_stock_with_a_zero_forecast_is_flagged_as_placement(self) -> None:
        result = recommend(
            _inputs(monthly_point_forecast=0.0, monthly_quantile_forecast=0.0,
                    usable_stock_on_hand=500.0)
        )
        assert result.days_of_cover is None
        assert any("placement question" in warning for warning in result.warnings)
