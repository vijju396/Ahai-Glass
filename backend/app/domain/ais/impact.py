"""What the forecasting is worth, separated into what was measured and what
is assumed.

This module exists because the obvious version of an "impact" panel is
prohibited here. The natural request - show the sales increase, the stock-out
reduction and the revenue we gained by implementing forecasting - cannot be
answered by measurement in this project, for three reasons that are structural
rather than fixable:

**No forecast month has elapsed.** The origin is the last observed month, so
every forecast period is still in the future. There is no post-implementation
actual to compare against a pre-implementation actual.

**There is no inventory-policy backtest.** Stock is a single snapshot with no
history, so nothing can say what stock-outs *would* have been under a
forecast-driven policy. `docs/DECISIONS.md` and the build contract both forbid
claiming one.

**A sales increase needs a counterfactual.** What AIS would have sold without
this system is not observable at all, at any horizon.

So this module computes two things and keeps them apart on the wire, because
collapsing them is exactly the failure mode:

- `measured` - forecast error against a naive carry-forward, by horizon, from
  the stored rolling-origin folds. Real, reproducible, and the honest basis
  for any claim.
- `projected` - what that error reduction could be worth, under assumptions
  the **viewer** sets. The defaults are deliberately conservative and are
  returned with the payload so the panel can print them. Nothing here is a
  measurement and the payload says so in `basis`.

The arithmetic is deliberately simple and legible. A planner has to be able to
follow it from the numbers on the panel, because a business case that cannot
be re-derived by the person being asked to fund it is not a business case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: The horizons the panel reports. Months ahead of the forecast origin.
#: One, three and six: the next order cycle, the quarter, and the planning
#: half-year.
REPORTED_HORIZONS: tuple[int, ...] = (1, 3, 6)

#: Below this many scored points a horizon's error is not reported. Six
#: folds x forty series still leaves thin cells at the long horizons, and a
#: WAPE over three points is noise presented as a measurement.
MIN_POINTS_PER_HORIZON = 12

#: Default assumptions. Conservative on purpose: a business case that only
#: works on optimistic inputs is not one. Every value is overridable by the
#: caller and echoed back in the payload.
DEFAULT_ASSUMPTIONS: dict[str, float] = {
    # Share of currently-unfilled demand that better forecasting could
    # realistically convert into a filled order. Not 100%: forecasting fixes
    # the planning half of a stock-out, never the supply half.
    "recovery_share": 0.30,
    # Contribution margin on recovered revenue.
    "margin_pct": 0.18,
    # Share of the measured error reduction that translates into less safety
    # stock for the same service level.
    "stock_efficiency_share": 0.50,
}

ASSUMPTION_LABELS: dict[str, str] = {
    "recovery_share": "Unfilled demand recoverable by better planning",
    "margin_pct": "Contribution margin on recovered revenue",
    "stock_efficiency_share": "Error reduction that converts to less safety stock",
}


@dataclass(frozen=True)
class HorizonAccuracy:
    """Measured error at one horizon, champion against naive."""

    horizon: int
    champion_wape: float | None
    baseline_wape: float | None
    points: int
    volume: float
    #: Positive means the champion is more accurate. Negative is kept and
    #: shown: a horizon where a naive carry-forward wins is the single most
    #: useful thing on this panel and hiding it would be dishonest.
    reduction_pct: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "champion_wape": self.champion_wape,
            "baseline_wape": self.baseline_wape,
            "reduction_pct": self.reduction_pct,
            "points": self.points,
            "volume": round(self.volume, 2),
            "reportable": self.points >= MIN_POINTS_PER_HORIZON,
        }


@dataclass
class Exposure:
    """What is currently at stake, from observed demand only."""

    ordered_units: float
    unfilled_units: float
    unfilled_rows: int
    demand_value: float
    fill_rate_pct: float | None
    series_count: int

    @property
    def value_per_unit(self) -> float | None:
        if self.ordered_units <= 0:
            return None
        return self.demand_value / self.ordered_units

    def as_dict(self) -> dict[str, Any]:
        return {
            "ordered_units": round(self.ordered_units, 2),
            "unfilled_units": round(self.unfilled_units, 2),
            "unfilled_rows": self.unfilled_rows,
            "demand_value": round(self.demand_value, 2),
            "fill_rate_pct": self.fill_rate_pct,
            "series_count": self.series_count,
            "value_per_unit": (
                round(self.value_per_unit, 2) if self.value_per_unit is not None else None
            ),
        }


@dataclass
class Projection:
    """One horizon's projected benefit. Not a measurement."""

    horizon: int
    months: int
    unfilled_units_in_window: float
    recoverable_units: float
    recovered_revenue: float
    recovered_margin: float
    safety_stock_released: float
    reduction_pct: float | None
    measured: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "months": self.months,
            "unfilled_units_in_window": round(self.unfilled_units_in_window, 1),
            "recoverable_units": round(self.recoverable_units, 1),
            "recovered_revenue": round(self.recovered_revenue, 2),
            "recovered_margin": round(self.recovered_margin, 2),
            "safety_stock_released": round(self.safety_stock_released, 2),
            "reduction_pct": self.reduction_pct,
            "measured": self.measured,
        }


@dataclass
class ImpactReport:
    horizons: list[HorizonAccuracy] = field(default_factory=list)
    exposure: Exposure | None = None
    projections: list[Projection] = field(default_factory=list)
    assumptions: dict[str, float] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    series_count: int = 0
    beaten_by_baseline: int = 0
    history_months: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "basis": (
                "Error reduction is measured from stored rolling-origin folds. "
                "Everything expressed in units or rupees is a projection from "
                "that measurement under the stated assumptions, not an observed "
                "outcome."
            ),
            "measured": {
                "horizons": [h.as_dict() for h in self.horizons],
                "series_count": self.series_count,
                "beaten_by_baseline": self.beaten_by_baseline,
                "history_months": self.history_months,
            },
            "exposure": self.exposure.as_dict() if self.exposure else None,
            "projections": [p.as_dict() for p in self.projections],
            "assumptions": self.assumptions,
            "assumption_labels": ASSUMPTION_LABELS,
            "caveats": self.caveats,
        }


def _wape(abs_error: float, volume: float) -> float | None:
    if volume <= 0:
        return None
    return 100.0 * abs_error / volume


def horizon_accuracy(
    champion_folds: Iterable[tuple[Sequence[int], Sequence[Any], Sequence[Any]]],
    baseline_folds: Iterable[tuple[Sequence[int], Sequence[Any], Sequence[Any]]],
) -> list[HorizonAccuracy]:
    """Volume-weighted WAPE per horizon for champion and baseline.

    Pooled across series rather than averaged over them. A mean of per-series
    percentages lets a tiny series with a 400% error dominate a branch that
    carries most of the volume; pooling absolute error over pooled volume
    answers the question a planner actually has, which is how wrong the
    forecast is about the units they must stock.
    """
    champ = _accumulate(champion_folds)
    base = _accumulate(baseline_folds)

    out: list[HorizonAccuracy] = []
    for horizon in sorted(set(champ) | set(base)):
        c_err, c_vol, c_n = champ.get(horizon, (0.0, 0.0, 0))
        b_err, b_vol, _ = base.get(horizon, (0.0, 0.0, 0))
        c_wape = _wape(c_err, c_vol)
        b_wape = _wape(b_err, b_vol)
        reduction = (
            round(100.0 * (b_wape - c_wape) / b_wape, 2)
            if c_wape is not None and b_wape is not None and b_wape > 0
            else None
        )
        out.append(
            HorizonAccuracy(
                horizon=horizon,
                champion_wape=round(c_wape, 2) if c_wape is not None else None,
                baseline_wape=round(b_wape, 2) if b_wape is not None else None,
                points=c_n,
                volume=c_vol,
                reduction_pct=reduction,
            )
        )
    return out


def _accumulate(
    folds: Iterable[tuple[Sequence[int], Sequence[Any], Sequence[Any]]],
) -> dict[int, tuple[float, float, int]]:
    acc: dict[int, list[float | int]] = {}
    for horizons, actuals, predictions in folds:
        for horizon, actual, prediction in zip(horizons, actuals, predictions):
            a = _to_float(actual)
            p = _to_float(prediction)
            if a is None or p is None or horizon is None:
                continue
            cell = acc.setdefault(int(horizon), [0.0, 0.0, 0])
            cell[0] = float(cell[0]) + abs(a - p)
            cell[1] = float(cell[1]) + abs(a)
            cell[2] = int(cell[2]) + 1
    return {k: (float(v[0]), float(v[1]), int(v[2])) for k, v in acc.items()}


def project(
    accuracy: Sequence[HorizonAccuracy],
    exposure: Exposure,
    assumptions: dict[str, float],
    *,
    history_months: int,
    horizons: Sequence[int] = REPORTED_HORIZONS,
) -> list[Projection]:
    """Translate measured error reduction into a projected benefit.

    The chain, in full, because it must be checkable from the panel:

        monthly unfilled  = unfilled units over the observed window / months
        window unfilled   = monthly unfilled x horizon months
        recoverable       = window unfilled x recovery_share x reduction_pct
        revenue           = recoverable x value per unit
        margin            = revenue x margin_pct

    `reduction_pct` is the only measured term. Everything else is either an
    observed total or an assumption the caller chose, which is why a horizon
    with no measured reduction returns zeros and is flagged `measured: False`
    rather than silently borrowing a neighbouring horizon's figure.
    """
    by_horizon = {a.horizon: a for a in accuracy}
    per_month = set_monthly_basis(exposure, history_months)

    recovery = float(assumptions.get("recovery_share", 0.0))
    margin = float(assumptions.get("margin_pct", 0.0))
    stock_share = float(assumptions.get("stock_efficiency_share", 0.0))
    unit_value = exposure.value_per_unit or 0.0

    out: list[Projection] = []
    for horizon in horizons:
        measured = by_horizon.get(horizon)
        reduction = (
            measured.reduction_pct
            if measured is not None
            and measured.reduction_pct is not None
            and measured.points >= MIN_POINTS_PER_HORIZON
            else None
        )
        window_unfilled = per_month * horizon
        if reduction is None or reduction <= 0:
            out.append(
                Projection(
                    horizon=horizon,
                    months=horizon,
                    unfilled_units_in_window=window_unfilled,
                    recoverable_units=0.0,
                    recovered_revenue=0.0,
                    recovered_margin=0.0,
                    safety_stock_released=0.0,
                    reduction_pct=reduction,
                    measured=reduction is not None,
                )
            )
            continue
        share = reduction / 100.0
        recoverable = window_unfilled * recovery * share
        revenue = recoverable * unit_value
        out.append(
            Projection(
                horizon=horizon,
                months=horizon,
                unfilled_units_in_window=window_unfilled,
                recoverable_units=recoverable,
                recovered_revenue=revenue,
                recovered_margin=revenue * margin,
                safety_stock_released=window_unfilled * share * stock_share * unit_value,
                reduction_pct=reduction,
                measured=True,
            )
        )
    return out


def set_monthly_basis(exposure: Exposure, history_months: int) -> float:
    """Unfilled units per month over the observed window."""
    if history_months <= 0:
        return 0.0
    return exposure.unfilled_units / history_months


def build_caveats(report: ImpactReport) -> list[str]:
    """The limits that must travel with every figure on this panel."""
    caveats = [
        "No forecast month has elapsed yet: history ends at the forecast "
        "origin, so nothing here is a realised outcome and no before/after "
        "comparison exists to make.",
        "There is no inventory-policy backtest in this project - stock is a "
        "single snapshot with no history - so the stock-out figures are "
        "projections from forecast error, never simulated policy results.",
        "A sales increase requires knowing what AIS would have sold without "
        "this system. That counterfactual is not observable, so no sales "
        "uplift is claimed.",
    ]
    weak = [
        h for h in report.horizons
        if h.reduction_pct is not None and h.reduction_pct <= 0
    ]
    if weak:
        names = ", ".join(f"month {h.horizon}" for h in weak)
        caveats.append(
            f"At {names} a naive carry-forward matched or beat the selected "
            "champion, so no benefit is projected there. The bar is shown at "
            "zero rather than hidden."
        )
    if report.beaten_by_baseline:
        caveats.append(
            f"{report.beaten_by_baseline} of {report.series_count} individual "
            "series are beaten by a non-registry baseline. Branch x SKU is the "
            "level stocking decisions are made at, so this tempers every "
            "figure above."
        )
    return caveats


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out
