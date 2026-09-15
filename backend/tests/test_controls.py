"""Structural controls, service measures and lead-time statistics."""

from __future__ import annotations

import pytest

from app.domain.ais.controls import (
    ControlInputs,
    LeadTimeStats,
    ServiceMeasures,
    evaluate_controls,
)
from app.models.datasets import ControlOutcome

EXPECTED = {
    "sales_rows": 1_703_042,
    "order_rows": 775_912,
    "stock_rows": 144_921,
    "product_master_rows": 2_417,
    "location_master_rows": 57,
    "sales_skus": 2_260,
    "series": 63_210,
    "normalized_depots": 53,
}


def _inputs(**overrides) -> ControlInputs:
    base = {
        "sales_rows": 1_703_042,
        "order_rows": 775_912,
        "stock_rows": 144_921,
        "product_master_rows": 2_417,
        "location_master_rows": 57,
        "canonical_sku_count": 2_260,
        "series_count": 63_210,
        "normalized_depot_count": 53,
        "product_master_coverage_pct": 99.9,
        # Measured shape: median 3, p95 6, max 27.
        "lead_time": LeadTimeStats([1] * 80 + [2] * 180 + [3] * 340 + [4] * 200
                                   + [5] * 130 + [6] * 45 + [9] * 20 + [27] * 5),
    }
    base.update(overrides)
    return ControlInputs(**base)


class TestControlSuite:
    def test_all_controls_pass_on_the_real_measured_values(self) -> None:
        results = evaluate_controls(_inputs(), EXPECTED, 0.5)
        failed = [r.code for r in results if r.failed]
        assert failed == []

    def test_every_control_is_reported_even_when_passing(self) -> None:
        """A control is never omitted - a missing row is indistinguishable from
        a control nobody ran."""
        results = evaluate_controls(_inputs(), EXPECTED, 0.5)
        codes = [result.code for result in results]
        assert codes == ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]

    def test_a_short_sales_read_fails_with_a_remediation(self) -> None:
        results = evaluate_controls(_inputs(sales_rows=822_030), EXPECTED, 0.5)
        s1 = next(result for result in results if result.code == "S1")
        assert s1.outcome is ControlOutcome.FAIL
        assert s1.measured == "822,030"
        assert s1.difference is not None and s1.difference.startswith("-881,012")
        assert s1.remediation and "sheet" in s1.remediation.lower()

    def test_row_counts_tolerate_a_tiny_drift(self) -> None:
        results = evaluate_controls(_inputs(sales_rows=1_703_100), EXPECTED, 0.5)
        assert next(r for r in results if r.code == "S1").outcome is ControlOutcome.PASS

    def test_the_sku_universe_admits_no_tolerance(self) -> None:
        """An off-by-one in S6 means the canonical key rule itself changed
        behaviour, so it fails even inside the row-count tolerance."""
        results = evaluate_controls(_inputs(canonical_sku_count=2_259), EXPECTED, 0.5)
        s6 = next(result for result in results if result.code == "S6")
        assert s6.outcome is ControlOutcome.FAIL
        assert s6.tolerance_pct == 0.0

    def test_using_oracle_no_as_the_key_fails_the_sku_control(self) -> None:
        """The exact failure rule C10 exists to prevent: 2,147 not 2,260."""
        results = evaluate_controls(_inputs(canonical_sku_count=2_147), EXPECTED, 0.5)
        s6 = next(result for result in results if result.code == "S6")
        assert s6.outcome is ControlOutcome.FAIL
        assert "2,147" in (s6.measured or "")
        assert s6.remediation and "Oracle No" in s6.remediation

    def test_the_series_universe_admits_no_tolerance(self) -> None:
        results = evaluate_controls(_inputs(series_count=63_209), EXPECTED, 0.5)
        assert next(r for r in results if r.code == "S7").outcome is ControlOutcome.FAIL

    def test_unnormalised_depots_fail(self) -> None:
        results = evaluate_controls(_inputs(normalized_depot_count=110), EXPECTED, 0.5)
        s8 = next(result for result in results if result.code == "S8")
        assert s8.outcome is ControlOutcome.FAIL
        assert s8.remediation and "UPPER" in s8.remediation

    def test_low_master_coverage_fails(self) -> None:
        results = evaluate_controls(_inputs(product_master_coverage_pct=71.0), EXPECTED, 0.5)
        assert next(r for r in results if r.code == "S9").outcome is ControlOutcome.FAIL

    def test_absent_coverage_is_not_evaluated_rather_than_passed(self) -> None:
        results = evaluate_controls(_inputs(product_master_coverage_pct=None), EXPECTED, 0.5)
        s9 = next(result for result in results if result.code == "S9")
        assert s9.outcome is ControlOutcome.NOT_EVALUATED
        assert not s9.failed

    def test_corrupt_lead_times_fail_their_controls(self) -> None:
        """The failure rule C14 exists to catch. If uncleaned despatch dates
        leak in, the distribution is dominated by garbage and both the median
        and the p95 leave their plausible bands."""
        corrupt = [-8763] * 200 + [-100] * 200 + [3] * 100 + [500] * 250 + [900] * 250
        results = evaluate_controls(_inputs(lead_time=LeadTimeStats(corrupt)), EXPECTED, 0.5)
        assert next(r for r in results if r.code == "S10").outcome is ControlOutcome.FAIL
        assert next(r for r in results if r.code == "S11").outcome is ControlOutcome.FAIL

    def test_an_empty_lead_time_sample_is_not_evaluated(self) -> None:
        results = evaluate_controls(_inputs(lead_time=LeadTimeStats([])), EXPECTED, 0.5)
        for code in ("S10", "S11"):
            assert next(r for r in results if r.code == code).outcome is ControlOutcome.NOT_EVALUATED

    def test_a_missing_expected_value_is_not_evaluated(self) -> None:
        results = evaluate_controls(_inputs(), {}, 0.5)
        s1 = next(result for result in results if result.code == "S1")
        assert s1.outcome is ControlOutcome.NOT_EVALUATED
        assert not s1.failed


class TestServiceMeasures:
    def test_net_and_gross_shortfall_differ_when_lines_over_deliver(self) -> None:
        """The real reason both must be reported: 9,498 lines shipped more than
        was ordered, so the two figures differ by 7.6%."""
        measures = ServiceMeasures()
        measures.observe(100, 80)   # 20 short
        measures.observe(100, 130)  # 30 over
        assert measures.net_shortfall == -10
        assert measures.gross_positive_shortfall == 20
        assert measures.over_delivered == 30
        assert measures.lines_with_shortfall == 1
        assert measures.lines_over_delivered == 1

    def test_reproduces_the_measured_network_totals(self) -> None:
        measures = ServiceMeasures()
        measures.total_ordered = 2_602_392
        measures.total_despatched = 2_133_961
        measures.gross_positive_shortfall = 504_298
        assert measures.net_shortfall == 468_431
        assert measures.gross_shortfall_pct == pytest.approx(19.38, abs=0.01)
        assert measures.net_fill_rate == pytest.approx(0.8199, abs=0.0001)

    def test_a_null_despatch_counts_as_nothing_shipped(self) -> None:
        """A null despatch quantity means nothing was despatched, not 'unknown,
        skip this line' - skipping would understate the shortfall."""
        measures = ServiceMeasures()
        measures.observe(50, None)
        assert measures.total_despatched == 0
        assert measures.gross_positive_shortfall == 50
        assert measures.lines_fully_unserved == 1

    def test_a_null_order_quantity_is_ignored(self) -> None:
        measures = ServiceMeasures()
        measures.observe(None, 10)
        assert measures.line_count == 0

    def test_fill_rate_is_none_rather_than_zero_when_nothing_was_ordered(self) -> None:
        assert ServiceMeasures().net_fill_rate is None
        assert ServiceMeasures().gross_shortfall_pct is None


class TestLeadTimeStats:
    def test_reproduces_the_measured_percentiles(self) -> None:
        """The measured distribution: median 3 days, p95 6, max 27."""
        stats = LeadTimeStats(
            [1] * 80 + [2] * 180 + [3] * 340 + [4] * 200 + [5] * 130
            + [6] * 45 + [9] * 20 + [27] * 5
        )
        assert stats.median == 3.0
        assert stats.p95 == 6.0
        assert stats.maximum == 27

    def test_counts_exclusions_rather_than_hiding_them(self) -> None:
        stats = LeadTimeStats([3, 3, 4], unparseable_dates=68, negative_excluded=216)
        assert stats.count == 3
        assert stats.as_dict()["unparseable_dates"] == 68
        assert stats.as_dict()["negative_excluded"] == 216

    def test_empty_sample_returns_none_not_zero(self) -> None:
        stats = LeadTimeStats([])
        assert stats.median is None
        assert stats.p95 is None
        assert stats.maximum is None
