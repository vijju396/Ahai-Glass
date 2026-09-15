"""Demand drift: how far recent demand has moved from its own baseline.

Drift here is a **measured property of the history**, not a model output. For
each month it compares a trailing window against the window before it and
reports the percentage shift. That series is what the chart draws.

## The projection, and what it is honestly worth

The request was to forecast when the next drift will happen. That is not a
thing this data can answer well, and saying so is more useful than inventing
a date, so the projection here is deliberately modest and deliberately
labelled:

- It fits an **ordinary least-squares line through the observed drift
  magnitude** and extrapolates to the threshold crossing.
- It is an extrapolation of a trend, **not a forecast from one of the 13
  models**. No model was fitted to drift; none was asked to predict it.
- It refuses to answer when the fit does not support one: too few points, a
  flat or shrinking trend, or a projected date beyond the horizon. In those
  cases `projectable` is false and `reason` says which.

## The measurement change that dominates this dataset

The panel switches source in Apr 2025: everything before is `sales_proxy`
(invoiced quantity), everything after is `order` (ordered quantity). A shift
measured across that boundary is partly a change of *measurement*, not of
demand. Every payload carries `measurement_change` so a reader can see which
points straddle it, and the projection is computed on the post-change window
only when enough of it exists - extrapolating a trend that is half an
artefact would be worse than not projecting at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

#: Months in each comparison window. Six gives a half-year against a half-year,
#: which is long enough to survive one odd month and short enough to still be
#: "recent" on a 28-month panel.
WINDOW_MONTHS = 6

#: Above this absolute shift, the average of the earlier window is a weak
#: description of the recent one. Not a threshold from the data - a stated
#: reading aid, drawn as a line so a reader can disagree with it.
MATERIAL_SHIFT_PCT = 20.0

#: The month the target source changes from sales proxy to real orders.
MEASUREMENT_CHANGE = "2025-04"

#: How far ahead a crossing may be projected. Beyond this the extrapolation is
#: further than the history it rests on.
MAX_PROJECTION_MONTHS = 12

#: Fewer post-change drift points than this and a trend line is noise.
MIN_POINTS_FOR_TREND = 5


@dataclass(frozen=True)
class DriftPoint:
    period: str
    recent_mean: float
    baseline_mean: float
    shift_pct: float
    straddles_measurement_change: bool


def _month_index(period: str) -> int:
    year, month = period.split("-")
    return int(year) * 12 + int(month) - 1


def _add_months(period: str, months: int) -> str:
    index = _month_index(period) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def drift_series(monthly: pd.Series, *, window: int = WINDOW_MONTHS) -> list[DriftPoint]:
    """Rolling shift of one window against the window before it.

    `monthly` is indexed by `YYYY-MM` and already aggregated to whatever scope
    the caller cares about.
    """
    periods = list(monthly.index)
    values = [float(v) for v in monthly.to_numpy()]
    points: list[DriftPoint] = []
    change_index = _month_index(MEASUREMENT_CHANGE)

    for end in range(2 * window - 1, len(periods)):
        recent = values[end - window + 1 : end + 1]
        baseline = values[end - 2 * window + 1 : end - window + 1]
        baseline_mean = float(np.mean(baseline)) if baseline else 0.0
        recent_mean = float(np.mean(recent)) if recent else 0.0
        if baseline_mean == 0:
            # Undefined, not zero: a shift from nothing has no percentage.
            continue
        window_start = _month_index(periods[end - 2 * window + 1])
        window_end = _month_index(periods[end])
        points.append(
            DriftPoint(
                period=periods[end],
                recent_mean=round(recent_mean, 1),
                baseline_mean=round(baseline_mean, 1),
                shift_pct=round(100.0 * (recent_mean - baseline_mean) / baseline_mean, 2),
                straddles_measurement_change=window_start < change_index <= window_end,
            )
        )
    return points


def project_next_crossing(
    points: list[DriftPoint],
    *,
    threshold: float = MATERIAL_SHIFT_PCT,
    max_months: int = MAX_PROJECTION_MONTHS,
) -> dict[str, Any]:
    """When the drift magnitude would cross `threshold`, if the trend holds.

    Returns `projectable: False` with a reason far more often than not, which
    is the correct behaviour: an extrapolation from four noisy points dressed
    up as a date is worse than admitting the data does not support one.
    """
    clean = [p for p in points if not p.straddles_measurement_change]
    if len(clean) < MIN_POINTS_FOR_TREND:
        return {
            "projectable": False,
            "reason": (
                f"Only {len(clean)} drift point(s) avoid the Apr 2025 measurement change. "
                f"A trend needs at least {MIN_POINTS_FOR_TREND}; fewer would be fitting a "
                "line to noise."
            ),
            "points_used": len(clean),
        }

    x = np.arange(len(clean), dtype=float)
    y = np.array([abs(p.shift_pct) for p in clean], dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    current = float(y[-1])

    # R^2, so the caller can see how much the line is worth.
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    r_squared = round(1.0 - ss_res / ss_tot, 3) if ss_tot > 0 else None

    base = {
        "points_used": len(clean),
        "slope_pct_per_month": round(float(slope), 3),
        "r_squared": r_squared,
        "current_shift_pct": round(current, 2),
        "threshold_pct": threshold,
        "from_period": clean[-1].period,
    }

    if current >= threshold:
        return base | {
            "projectable": False,
            "already_crossed": True,
            "reason": (
                f"Drift is already at {current:.1f}%, above the {threshold:.0f}% reading "
                "aid. There is nothing to project to - it has happened."
            ),
        }
    if slope <= 0:
        return base | {
            "projectable": False,
            "reason": (
                f"Drift magnitude is flat or shrinking ({slope:+.2f} pp per month), so on "
                "this trend it never reaches the threshold. A projection would have to "
                "invent a turning point the data does not show."
            ),
        }

    months = (threshold - current) / slope
    if months > max_months:
        return base | {
            "projectable": False,
            "reason": (
                f"On the current trend the threshold is about {months:.0f} months away, "
                f"beyond the {max_months}-month limit - further ahead than the "
                f"{len(clean)} months of drift history it rests on."
            ),
        }

    return base | {
        "projectable": True,
        "months_ahead": round(float(months), 1),
        "expected_period": _add_months(clean[-1].period, int(round(months))),
        "basis": (
            "Ordinary least-squares line through the observed drift magnitude, "
            "extrapolated to the threshold. This is a trend extrapolation, not a "
            "forecast from any of the 13 registered models."
        ),
    }


def analyse(monthly: pd.Series, *, scope_label: str) -> dict[str, Any]:
    """Everything the drift panel shows for one scope."""
    if monthly.empty or len(monthly) < 2 * WINDOW_MONTHS:
        return {
            "empty": True,
            "reason": (
                f"Drift compares a {WINDOW_MONTHS}-month window against the "
                f"{WINDOW_MONTHS} before it, so it needs at least "
                f"{2 * WINDOW_MONTHS} months. This scope has {len(monthly)}."
            ),
            "scope": scope_label,
        }

    points = drift_series(monthly)
    if not points:
        return {
            "empty": True,
            "reason": "Every baseline window sums to zero, so no percentage shift is defined.",
            "scope": scope_label,
        }

    latest = points[-1]
    return {
        "empty": False,
        "scope": scope_label,
        "window_months": WINDOW_MONTHS,
        "threshold_pct": MATERIAL_SHIFT_PCT,
        "measurement_change": MEASUREMENT_CHANGE,
        "points": [
            {
                "period": p.period,
                "shift_pct": p.shift_pct,
                "recent_mean": p.recent_mean,
                "baseline_mean": p.baseline_mean,
                "straddles_measurement_change": p.straddles_measurement_change,
            }
            for p in points
        ],
        "latest": {
            "period": latest.period,
            "shift_pct": latest.shift_pct,
            "recent_mean": latest.recent_mean,
            "baseline_mean": latest.baseline_mean,
            "is_material": abs(latest.shift_pct) >= MATERIAL_SHIFT_PCT,
        },
        "projection": project_next_crossing(points),
        "caveats": [
            f"Drift compares the last {WINDOW_MONTHS} months against the "
            f"{WINDOW_MONTHS} before them. It is measured from the panel, not "
            "predicted by a model.",
            f"The panel changes source at {MEASUREMENT_CHANGE}: earlier months are "
            "invoiced sales proxy, later months are real orders. Points whose windows "
            "straddle that date are marked, and the projection excludes them — part of "
            "the shift there is a change of measurement, not of demand.",
            f"The {MATERIAL_SHIFT_PCT:.0f}% line is a stated reading aid, not a threshold "
            "derived from this data.",
            "Any projection is a straight line through observed drift, extrapolated. It "
            "is not a forecast from any of the 13 registered models.",
        ],
    }
