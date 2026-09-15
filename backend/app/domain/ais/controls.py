"""Structural controls (docs/VALIDATION_REPORT.md SS1) and the service measures.

A control failure is never swallowed. Every control produces an explicit
outcome with its expected value, its measured value, the difference, and a
remediation; the ingestion version is marked COMPLETED_WITH_FAILURES so nothing
downstream can treat the data as clean by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.datasets import ControlOutcome


@dataclass
class ControlResult:
    code: str
    description: str
    expected: str | None
    measured: str | None
    outcome: ControlOutcome
    difference: str | None = None
    tolerance_pct: float | None = None
    remediation: str | None = None

    @property
    def failed(self) -> bool:
        return self.outcome is ControlOutcome.FAIL


def _count_control(
    code: str,
    description: str,
    expected: int | None,
    measured: int,
    *,
    tolerance_pct: float,
    remediation: str,
    exact: bool = False,
) -> ControlResult:
    """Compare a measured count against its expected control value.

    `exact=True` means the control admits no tolerance at all - used for the
    SKU and series universe, where an off-by-one indicates the canonical key
    rule itself has changed behaviour.
    """
    if expected is None:
        return ControlResult(
            code, description, None, f"{measured:,}", ControlOutcome.NOT_EVALUATED,
            remediation="No expected value configured for this control.",
        )
    delta = measured - expected
    if delta == 0:
        outcome = ControlOutcome.PASS
    elif exact:
        outcome = ControlOutcome.FAIL
    else:
        drift_pct = abs(delta) / expected * 100 if expected else 100.0
        outcome = ControlOutcome.PASS if drift_pct <= tolerance_pct else ControlOutcome.FAIL
    difference = None if delta == 0 else f"{delta:+,} ({delta / expected * 100:+.3f}%)"
    return ControlResult(
        code=code,
        description=description,
        expected=f"{expected:,}",
        measured=f"{measured:,}",
        outcome=outcome,
        difference=difference,
        tolerance_pct=0.0 if exact else tolerance_pct,
        remediation=remediation if outcome is ControlOutcome.FAIL else None,
    )


# --------------------------------------------------------------------------
# Service measures (docs/AIS_DOMAIN_RULES.md SS2)
# --------------------------------------------------------------------------

@dataclass
class ServiceMeasures:
    """Net and gross shortfall are reported SEPARATELY and deliberately.

    They differ by 7.6% because 9,498 order lines despatched more than was
    ordered. Collapsing them into one number hides that entirely.
    """

    total_ordered: int = 0
    total_despatched: int = 0
    gross_positive_shortfall: int = 0
    over_delivered: int = 0
    lines_fully_unserved: int = 0
    lines_with_shortfall: int = 0
    lines_over_delivered: int = 0
    line_count: int = 0

    @property
    def net_shortfall(self) -> int:
        return self.total_ordered - self.total_despatched

    @property
    def net_fill_rate(self) -> float | None:
        if not self.total_ordered:
            return None
        return self.total_despatched / self.total_ordered

    @property
    def gross_shortfall_pct(self) -> float | None:
        if not self.total_ordered:
            return None
        return self.gross_positive_shortfall / self.total_ordered * 100

    def observe(self, ordered: float | None, despatched: float | None) -> None:
        if ordered is None:
            return
        # A null despatch quantity means nothing shipped, not "unknown, skip".
        served = 0.0 if despatched is None else despatched
        self.line_count += 1
        self.total_ordered += int(ordered)
        self.total_despatched += int(served)
        gap = ordered - served
        if gap > 0:
            self.gross_positive_shortfall += int(gap)
            self.lines_with_shortfall += 1
        elif gap < 0:
            self.over_delivered += int(-gap)
            self.lines_over_delivered += 1
        if served == 0:
            self.lines_fully_unserved += 1

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "total_ordered": self.total_ordered,
            "total_despatched": self.total_despatched,
            "net_shortfall": self.net_shortfall,
            "gross_positive_shortfall": self.gross_positive_shortfall,
            "over_delivered_qty": self.over_delivered,
            "net_fill_rate": self.net_fill_rate,
            "gross_shortfall_pct": self.gross_shortfall_pct,
            "lines_total": self.line_count,
            "lines_fully_unserved": self.lines_fully_unserved,
            "lines_with_shortfall": self.lines_with_shortfall,
            "lines_over_delivered": self.lines_over_delivered,
        }


# --------------------------------------------------------------------------
# Lead-time statistics (rule C14)
# --------------------------------------------------------------------------

@dataclass
class LeadTimeStats:
    """Computed only on CLEANED despatch dates.

    The raw column contains `0000-00-00` and values producing lead times down
    to -8,763 days. Uncleaned, Roorkee's standard deviation is 132 days
    instead of ~1.5, so every excluded value is counted and reported.
    """

    values: list[int]
    unparseable_dates: int = 0
    negative_excluded: int = 0

    @property
    def count(self) -> int:
        return len(self.values)

    def percentile(self, fraction: float) -> float | None:
        if not self.values:
            return None
        ordered = sorted(self.values)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return float(ordered[index])

    @property
    def median(self) -> float | None:
        return self.percentile(0.5)

    @property
    def p95(self) -> float | None:
        return self.percentile(0.95)

    @property
    def maximum(self) -> int | None:
        return max(self.values) if self.values else None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "count": self.count,
            "median_days": self.median,
            "p95_days": self.p95,
            "max_days": self.maximum,
            "unparseable_dates": self.unparseable_dates,
            "negative_excluded": self.negative_excluded,
        }


# --------------------------------------------------------------------------
# The control suite
# --------------------------------------------------------------------------

@dataclass
class ControlInputs:
    sales_rows: int
    order_rows: int
    stock_rows: int
    product_master_rows: int
    location_master_rows: int
    canonical_sku_count: int
    series_count: int
    normalized_depot_count: int
    product_master_coverage_pct: float | None
    lead_time: LeadTimeStats


def evaluate_controls(inputs: ControlInputs, expected: dict[str, int], tolerance_pct: float) -> list[ControlResult]:
    """Produce every control result, pass or fail. Nothing is omitted."""
    results: list[ControlResult] = [
        _count_control(
            "S1", "Sales invoice-line rows", expected.get("sales_rows"), inputs.sales_rows,
            tolerance_pct=tolerance_pct,
            remediation="Re-read both .xlsb sheets. A short count usually means one sheet failed to stream.",
        ),
        _count_control(
            "S2", "Order lines", expected.get("order_rows"), inputs.order_rows,
            tolerance_pct=tolerance_pct,
            remediation="Confirm the order workbook's active sheet is 'Receipts (Lead Time)'.",
        ),
        _count_control(
            "S3", "Stock snapshot rows", expected.get("stock_rows"), inputs.stock_rows,
            tolerance_pct=tolerance_pct,
            remediation="The stock sheet has a title row above its header; skip exactly one row.",
        ),
        _count_control(
            "S4", "Product-master rows", expected.get("product_master_rows"),
            inputs.product_master_rows, tolerance_pct=tolerance_pct,
            remediation="Check the substitution workbook has not been re-saved with extra rows.",
        ),
        _count_control(
            "S5", "Location-master rows (footer excluded)",
            expected.get("location_master_rows"), inputs.location_master_rows,
            tolerance_pct=tolerance_pct,
            remediation="Row 58 is a footer whose values sit in the wrong columns; rule C15 removes it.",
        ),
        _count_control(
            "S6", "Distinct canonical SKUs", expected.get("sales_skus"),
            inputs.canonical_sku_count, tolerance_pct=0.0, exact=True,
            remediation=(
                "The canonical key rule (C8) has changed behaviour. It must strip a trailing "
                ".AFM/.AF, then a trailing dot, then TRIM again. Raw Oracle No yields 2,147, not 2,260."
            ),
        ),
        _count_control(
            "S7", "Branch x SKU series", expected.get("series"), inputs.series_count,
            tolerance_pct=0.0, exact=True,
            remediation=(
                "Series count derives from canonical branch x canonical SKU. Check branch "
                "normalisation (C6) and the canonical key (C8) independently."
            ),
        ),
        _count_control(
            "S8", "Normalized order depots", expected.get("normalized_depots"),
            inputs.normalized_depot_count, tolerance_pct=tolerance_pct,
            remediation="Depot values need TRIM+UPPER; 110 raw spellings must collapse to 53.",
        ),
    ]

    # S9 - product-master coverage
    coverage = inputs.product_master_coverage_pct
    if coverage is None:
        results.append(
            ControlResult(
                "S9", "Product-master coverage of order lines (line-weighted, via Oracle No)",
                "~99.9%", None,
                ControlOutcome.NOT_EVALUATED,
                remediation="Coverage needs both the order file and the product master.",
            )
        )
    else:
        results.append(
            ControlResult(
                "S9", "Product-master coverage of order lines (line-weighted, via Oracle No)",
                ">= 99.0%", f"{coverage:.3f}%",
                ControlOutcome.PASS if coverage >= 99.0 else ControlOutcome.FAIL,
                difference=None if coverage >= 99.0 else f"{coverage - 99.0:+.2f} pp",
                remediation=(
                    None if coverage >= 99.0
                    else (
                        "Order lines are not joining the product master. Coverage is "
                        "line-weighted and keyed on Oracle No, which is the measured join "
                        "key for the order file (99.909% vs 93.699% via Material Code). "
                        "Check that key before relaxing this control."
                    )
                ),
            )
        )

    # S10 / S11 - lead time, on cleaned dates only
    median = inputs.lead_time.median
    results.append(
        ControlResult(
            "S10", "Median order-to-despatch lead time (cleaned dates)", "3 days",
            None if median is None else f"{median:.0f} days",
            ControlOutcome.NOT_EVALUATED if median is None
            else (ControlOutcome.PASS if 2 <= median <= 4 else ControlOutcome.FAIL),
            remediation=(
                None if median is not None and 2 <= median <= 4
                else "Lead time must be computed only on parseable despatch dates (rule C14)."
            ),
        )
    )
    p95 = inputs.lead_time.p95
    results.append(
        ControlResult(
            "S11", "95th-percentile lead time (cleaned dates)", "6 days",
            None if p95 is None else f"{p95:.0f} days",
            ControlOutcome.NOT_EVALUATED if p95 is None
            else (ControlOutcome.PASS if 4 <= p95 <= 8 else ControlOutcome.FAIL),
            remediation=(
                None if p95 is not None and 4 <= p95 <= 8
                else "A wild p95 means corrupt despatch dates leaked into the statistic (rule C14)."
            ),
        )
    )
    return results
