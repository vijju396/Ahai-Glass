"""Period grids and explicit-zero materialisation.

Generic and dataset-agnostic. The one idea here is that **an absent month and
a zero month are different facts**, and which one applies depends on whether
the series was active. Collapsing them is the most damaging mistake available
on a panel that is 62% zeros:

- Before a series' first observation it did not exist. Those months are absent,
  not zero, and materialising them would invent history.
- After its first observation, a month with no demand is a real observation of
  zero. Leaving it out would hide the sparsity the model has to learn, and
  would leave `shift`-based lags counting observations instead of months.
- Trailing zeros are the obsolescence signal. They are kept, not trimmed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


def month_index(period: str) -> int:
    """Turn `YYYY-MM` into a monotonic month counter.

    Used instead of a date so lag arithmetic is integer arithmetic - no
    timezone, no day-of-month, no DST.
    """
    year, month = period.split("-")
    return int(year) * 12 + (int(month) - 1)


def index_to_period(index: int) -> str:
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


@dataclass
class GridStats:
    series_count: int = 0
    observed_rows: int = 0
    materialised_zero_rows: int = 0
    total_rows: int = 0
    first_period: str | None = None
    last_period: str | None = None

    @property
    def zero_share(self) -> float | None:
        if not self.total_rows:
            return None
        return self.materialised_zero_rows / self.total_rows

    def as_dict(self) -> dict[str, object]:
        return {
            "series_count": self.series_count,
            "observed_rows": self.observed_rows,
            "materialised_zero_rows": self.materialised_zero_rows,
            "total_rows": self.total_rows,
            "materialised_share": self.zero_share,
            "first_period": self.first_period,
            "last_period": self.last_period,
        }


def build_period_grid(
    observations: pd.DataFrame,
    *,
    series_col: str = "series_id",
    period_col: str = "period_index",
    panel_end: int,
    start_policy: str = "first_observation",
) -> tuple[pd.DataFrame, GridStats]:
    """Expand observations into a gap-free monthly grid per series.

    `start_policy`:

    - `first_observation` (default) - each series starts at its own first
      observed month. A series listed in April 2026 gets no invented history
      back to April 2024.
    - `panel_start` - every series starts at the panel's earliest month. Only
      correct when every series genuinely existed throughout.

    Returns the grid with an `is_materialised` flag, so a downstream consumer
    can always tell an observed row from a filled zero.
    """
    if observations.empty:
        return observations.copy(), GridStats()

    if start_policy not in {"first_observation", "panel_start"}:
        raise ValueError(f"Unknown start_policy {start_policy!r}.")

    bounds = observations.groupby(series_col, sort=False, observed=True)[period_col].min()
    panel_start = int(observations[period_col].min())
    if start_policy == "panel_start":
        bounds = bounds.map(lambda _: panel_start)

    frames: list[pd.DataFrame] = []
    for series_id, start in bounds.items():
        start_index = int(start)
        if start_index > panel_end:
            # A series first seen after the panel end contributes nothing.
            continue
        frames.append(
            pd.DataFrame(
                {
                    series_col: series_id,
                    period_col: range(start_index, panel_end + 1),
                }
            )
        )
    if not frames:
        return observations.iloc[0:0].copy(), GridStats()

    grid = pd.concat(frames, ignore_index=True)
    merged = grid.merge(observations, on=[series_col, period_col], how="left")
    # Materialisation is decided by whether the (series, period) key was
    # observed, not by scanning for NaN. A caller that passes only the key
    # columns - which is the normal case, since the values are joined
    # afterwards - produces no NaN at all, and a NaN check would then report
    # every filled month as observed.
    observed_keys = set(
        map(tuple, observations[[series_col, period_col]].itertuples(index=False, name=None))
    )
    merged["is_materialised"] = ~pd.Series(
        list(map(tuple, merged[[series_col, period_col]].itertuples(index=False, name=None))),
        index=merged.index,
    ).isin(observed_keys)

    stats = GridStats(
        series_count=int(merged[series_col].nunique()),
        observed_rows=int((~merged["is_materialised"]).sum()),
        materialised_zero_rows=int(merged["is_materialised"].sum()),
        total_rows=len(merged),
        first_period=index_to_period(int(merged[period_col].min())),
        last_period=index_to_period(int(merged[period_col].max())),
    )
    return merged, stats


def summarise_sparsity(
    panel: pd.DataFrame,
    *,
    series_col: str = "series_id",
    target_col: str = "target",
) -> dict[str, object]:
    """Sparsity facts a modelling decision actually turns on.

    ADI and CV-squared are the Syntetos-Boylan inputs; they are reported here
    as descriptive statistics, not used to select a method, because method
    routing in this project is by value class (docs/MODEL_INVENTORY.md SS2).
    """
    if panel.empty:
        return {}

    grouped = panel.groupby(series_col, sort=False, observed=True)[target_col]
    observed_months = grouped.size()
    nonzero_months = grouped.apply(lambda values: int((values != 0).sum()))

    # Average demand interval: months per non-zero observation.
    adi = (observed_months / nonzero_months.replace(0, pd.NA)).astype("Float64")

    def _cv_squared(values: pd.Series) -> float | None:
        nonzero = values[values != 0]
        if len(nonzero) < 2:
            return None
        mean = nonzero.mean()
        if not mean:
            return None
        return float((nonzero.std(ddof=0) / mean) ** 2)

    cv2 = grouped.apply(_cv_squared).astype("Float64")

    total_cells = len(panel)
    zero_cells = int((panel[target_col] == 0).sum())
    return {
        "series_count": int(observed_months.size),
        "total_cells": total_cells,
        "zero_cells": zero_cells,
        "zero_cell_share": zero_cells / total_cells if total_cells else None,
        "series_with_no_demand": int((nonzero_months == 0).sum()),
        "series_with_one_nonzero_month": int((nonzero_months == 1).sum()),
        "series_with_12_plus_nonzero_months": int((nonzero_months >= 12).sum()),
        "median_observed_months": float(observed_months.median()),
        "median_nonzero_months": float(nonzero_months.median()),
        "median_adi": None if adi.isna().all() else float(adi.median()),
        "median_cv_squared": None if cv2.isna().all() else float(cv2.median()),
    }
