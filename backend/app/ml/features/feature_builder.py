"""Leakage-safe feature construction for direct multi-horizon forecasting.

Generic and dataset-agnostic: nothing here knows an AIS column name. It takes a
long panel of `(series_id, period_index, target)` and produces origin features
plus a direct multi-horizon training frame.

**The convention, stated once because every off-by-one here is a leak.**

Features are computed *as of a forecast origin* `o`, using only observations at
`o` and earlier. `lag_1` is the value AT the origin - the most recent
observation available when the forecast is made - so `lag_k = target[o-(k-1)]`.
That matches both reference implementations, where `lag_1 = history[-1]` and
`history` holds everything known at prediction time
(Meriton `_xgb_features`, Sodexo `_lag`).

A training row is `(origin o, horizon h)` with `y = target[o+h]`. Because
`h >= 1`, a feature drawn from `<= o` can never contain the target being
predicted. `rolling_3` at origin `o` is the mean over `[o-2, o-1, o]`, and
`same_month_last_year` is `target[o+h-12]` - the same calendar month as the
TARGET, which is knowable at `o` whenever `h <= 12`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

#: Lags in months back from the forecast origin. `lag_1` is the origin's own
#: value. Ported from the AIS feature list (docs/DATA_CONTRACT.md SS4).
LAG_MONTHS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 9, 12)

#: Rolling windows, in months, ending at and including the origin.
ROLLING_WINDOWS: tuple[int, ...] = (3, 6, 12)

#: Windows over which non-zero observations are counted.
NONZERO_WINDOWS: tuple[int, ...] = (6, 12)

#: The horizons a single fitted model answers, because horizon is a feature.
DEFAULT_HORIZONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)


@dataclass
class FeatureSpec:
    name: str
    kind: str
    definition: str
    uses_target_history: bool
    max_lookback_months: int


@dataclass
class FeatureManifest:
    """What the model was actually fed, and how each value was derived.

    Persisted alongside the panel so a forecast can be explained later without
    re-deriving the feature code.
    """

    specs: list[FeatureSpec] = field(default_factory=list)
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    lag_convention: str = (
        "lag_1 is the value AT the forecast origin - the most recent observation "
        "available when the forecast is made. lag_k = target[origin-(k-1)]."
    )

    @property
    def feature_names(self) -> list[str]:
        return [spec.name for spec in self.specs]

    @property
    def max_lookback_months(self) -> int:
        return max((spec.max_lookback_months for spec in self.specs), default=0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lag_convention": self.lag_convention,
            "horizons": list(self.horizons),
            "max_lookback_months": self.max_lookback_months,
            "feature_count": len(self.specs),
            "features": [
                {
                    "name": spec.name,
                    "kind": spec.kind,
                    "definition": spec.definition,
                    "uses_target_history": spec.uses_target_history,
                    "max_lookback_months": spec.max_lookback_months,
                }
                for spec in self.specs
            ],
        }


def build_feature_manifest(
    *,
    static_columns: tuple[str, ...] = (),
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> FeatureManifest:
    specs: list[FeatureSpec] = []

    for lag in LAG_MONTHS:
        specs.append(
            FeatureSpec(
                name=f"lag_{lag}",
                kind="lag",
                definition=(
                    f"target at origin-{lag - 1} months"
                    + (" (the origin's own value)" if lag == 1 else "")
                ),
                uses_target_history=True,
                max_lookback_months=lag - 1,
            )
        )
    for window in ROLLING_WINDOWS:
        specs.append(
            FeatureSpec(
                name=f"rolling_mean_{window}",
                kind="rolling",
                definition=f"mean of target over the {window} months ending at the origin",
                uses_target_history=True,
                max_lookback_months=window - 1,
            )
        )
        specs.append(
            FeatureSpec(
                name=f"rolling_std_{window}",
                kind="rolling",
                definition=(
                    f"population std of target over the {window} months ending at "
                    "the origin"
                ),
                uses_target_history=True,
                max_lookback_months=window - 1,
            )
        )
    for window in NONZERO_WINDOWS:
        specs.append(
            FeatureSpec(
                name=f"nonzero_count_{window}",
                kind="sparsity",
                definition=(
                    f"count of non-zero target values in the {window} months ending "
                    "at the origin"
                ),
                uses_target_history=True,
                max_lookback_months=window - 1,
            )
        )
    specs.extend(
        [
            FeatureSpec(
                name="consecutive_zero_months",
                kind="sparsity",
                definition=(
                    "length of the unbroken run of zero-target months ending at the "
                    "origin; 0 when the origin itself is non-zero"
                ),
                uses_target_history=True,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="trend_3_minus_6",
                kind="trend",
                definition="rolling_mean_3 minus rolling_mean_6, both as of the origin",
                uses_target_history=True,
                max_lookback_months=5,
            ),
            FeatureSpec(
                name="same_month_last_year",
                kind="seasonal",
                definition=(
                    "target 12 months before the TARGET period, i.e. origin+horizon-12; "
                    "known at the origin whenever horizon <= 12"
                ),
                uses_target_history=True,
                max_lookback_months=11,
            ),
            FeatureSpec(
                name="calendar_month",
                kind="calendar",
                definition="calendar month (1-12) of the TARGET period; future-known",
                uses_target_history=False,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="horizon",
                kind="horizon",
                definition=(
                    "months ahead, 1..H. A feature, so one fitted model answers every "
                    "horizon (direct multi-horizon)"
                ),
                uses_target_history=False,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="origin_month",
                kind="calendar",
                definition="calendar month (1-12) of the origin period; future-known",
                uses_target_history=False,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="series_age_months",
                kind="history",
                definition="observed months for this series up to and including the origin",
                uses_target_history=True,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="origin_is_censored",
                kind="provenance",
                definition=(
                    "whether the origin period's demand was not fully served, so true "
                    "demand there was at least the observed value"
                ),
                uses_target_history=True,
                max_lookback_months=0,
            ),
            FeatureSpec(
                name="origin_target_source",
                kind="provenance",
                definition=(
                    "which source supplied the origin's observation: the true order "
                    "book, or the labelled sales proxy"
                ),
                uses_target_history=True,
                max_lookback_months=0,
            ),
        ]
    )
    for column in static_columns:
        specs.append(
            FeatureSpec(
                name=column,
                kind="static_attribute",
                definition=(
                    "constant per series, so knowable in advance for every horizon"
                ),
                uses_target_history=False,
                max_lookback_months=0,
            )
        )
    return FeatureManifest(specs=specs, horizons=horizons)


def _consecutive_zeros(values: np.ndarray) -> np.ndarray:
    """Length of the unbroken zero run ending at each position, inclusive.

    Vectorised over one series' ordered values. A non-zero at position i gives
    0; a zero gives 1 + the run ending at i-1.
    """
    is_zero = (values == 0).astype(np.int64)
    out = np.zeros(len(values), dtype=np.int64)
    run = 0
    for index, zero in enumerate(is_zero):
        run = run + 1 if zero else 0
        out[index] = run
    return out


def build_origin_features(
    panel: pd.DataFrame,
    *,
    series_col: str = "series_id",
    period_col: str = "period_index",
    target_col: str = "target",
    censored_col: str | None = "is_censored",
    source_col: str | None = "target_source",
) -> pd.DataFrame:
    """One row per (series, origin) with every history-derived feature.

    Every value uses observations at the origin or earlier. The panel must be a
    complete, gap-free period grid per series - `build_period_grid` guarantees
    that - because `shift` counts rows, not months, and a missing month would
    silently make `lag_2` mean "two observations back" instead of "two months
    back".
    """
    if panel.empty:
        return panel.copy()

    frame = panel.sort_values([series_col, period_col], kind="mergesort").reset_index(drop=True)
    _assert_gapless(frame, series_col=series_col, period_col=period_col)

    grouped = frame.groupby(series_col, sort=False, observed=True)
    target = frame[target_col].astype("float64")

    features = pd.DataFrame(
        {
            series_col: frame[series_col],
            period_col: frame[period_col],
        }
    )

    # lag_1 is the origin's own value, so the shift is (lag - 1).
    for lag in LAG_MONTHS:
        features[f"lag_{lag}"] = grouped[target_col].shift(lag - 1).astype("float64")

    for window in ROLLING_WINDOWS:
        rolling = grouped[target_col].rolling(window, min_periods=1)
        features[f"rolling_mean_{window}"] = rolling.mean().reset_index(level=0, drop=True)
        # Population std (ddof=0) matches the reference implementations'
        # `statistics.pstdev`, and gives 0 rather than NaN for a single value.
        features[f"rolling_std_{window}"] = (
            rolling.std(ddof=0).reset_index(level=0, drop=True).fillna(0.0)
        )

    nonzero = (target != 0).astype("float64")
    nonzero_frame = pd.DataFrame({series_col: frame[series_col], "_nz": nonzero})
    nonzero_grouped = nonzero_frame.groupby(series_col, sort=False, observed=True)
    for window in NONZERO_WINDOWS:
        features[f"nonzero_count_{window}"] = (
            nonzero_grouped["_nz"]
            .rolling(window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )

    features["consecutive_zero_months"] = (
        grouped[target_col]
        .transform(lambda values: _consecutive_zeros(values.to_numpy(dtype="float64")))
        .astype("int64")
    )
    features["trend_3_minus_6"] = (
        features["rolling_mean_3"] - features["rolling_mean_6"]
    )
    features["series_age_months"] = grouped.cumcount().astype("int64") + 1
    features["origin_month"] = frame[period_col].mod(12).add(1).astype("int64")

    if censored_col and censored_col in frame.columns:
        features["origin_is_censored"] = frame[censored_col].astype("int64")
    else:
        features["origin_is_censored"] = 0
    if source_col and source_col in frame.columns:
        features["origin_target_source"] = frame[source_col].astype("string")
    else:
        features["origin_target_source"] = pd.Series(
            ["unknown"] * len(frame), dtype="string"
        )

    return features


def build_training_frame(
    panel: pd.DataFrame,
    origin_features: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    series_col: str = "series_id",
    period_col: str = "period_index",
    target_col: str = "target",
    static_columns: tuple[str, ...] = (),
    max_origin_period: int | None = None,
    min_series_age: int = 1,
) -> pd.DataFrame:
    """The direct multi-horizon training set: one row per (series, origin, horizon).

    `max_origin_period` is the training cut. Origins after it are excluded, and
    so is any row whose target period falls after it - that is what makes a
    rolling-origin fold honest rather than merely chronological-looking.
    """
    if panel.empty or origin_features.empty:
        return pd.DataFrame()

    targets = panel[[series_col, period_col, target_col]].copy()
    targets = targets.rename(columns={period_col: "_target_period", target_col: "y"})

    statics = None
    if static_columns:
        present = [column for column in static_columns if column in panel.columns]
        if present:
            statics = (
                panel[[series_col, *present]]
                .drop_duplicates(subset=[series_col], keep="last")
                .reset_index(drop=True)
            )

    # same_month_last_year is indexed on the TARGET period, not the origin.
    seasonal = panel[[series_col, period_col, target_col]].copy()
    seasonal = seasonal.rename(
        columns={period_col: "_seasonal_period", target_col: "same_month_last_year"}
    )

    rows: list[pd.DataFrame] = []
    for horizon in horizons:
        block = origin_features.copy()
        block["horizon"] = horizon
        block["_target_period"] = block[period_col] + horizon

        block = block.merge(targets, on=[series_col, "_target_period"], how="inner")

        block["_seasonal_period"] = block["_target_period"] - 12
        block = block.merge(
            seasonal, on=[series_col, "_seasonal_period"], how="left"
        )

        block["calendar_month"] = block["_target_period"].mod(12).add(1).astype("int64")
        rows.append(block)

    frame = pd.concat(rows, ignore_index=True)

    if max_origin_period is not None:
        # Both bounds matter. Filtering only the origin would let a horizon-6
        # row read a target six months past the cut.
        frame = frame[
            (frame[period_col] <= max_origin_period)
            & (frame["_target_period"] <= max_origin_period)
        ]

    if min_series_age > 1 and "series_age_months" in frame.columns:
        frame = frame[frame["series_age_months"] >= min_series_age]

    if statics is not None:
        frame = frame.merge(statics, on=series_col, how="left")

    frame = frame.rename(columns={period_col: "origin_period", "_target_period": "target_period"})
    frame = frame.drop(columns=["_seasonal_period"], errors="ignore")
    return frame.sort_values(
        [series_col, "origin_period", "horizon"], kind="mergesort"
    ).reset_index(drop=True)


def build_scoring_frame(
    panel: pd.DataFrame,
    origin_features: pd.DataFrame,
    *,
    origin_period: int,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    series_col: str = "series_id",
    period_col: str = "period_index",
    target_col: str = "target",
    static_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Future rows to forecast: one per (series, horizon) from a single origin.

    Carries no `y`, because those periods have not happened.
    """
    at_origin = origin_features[origin_features[period_col] == origin_period]
    if at_origin.empty:
        return pd.DataFrame()

    seasonal = panel[[series_col, period_col, target_col]].rename(
        columns={period_col: "_seasonal_period", target_col: "same_month_last_year"}
    )
    statics = None
    if static_columns:
        present = [column for column in static_columns if column in panel.columns]
        if present:
            statics = (
                panel[[series_col, *present]]
                .drop_duplicates(subset=[series_col], keep="last")
                .reset_index(drop=True)
            )

    rows: list[pd.DataFrame] = []
    for horizon in horizons:
        block = at_origin.copy()
        block["horizon"] = horizon
        block["target_period"] = origin_period + horizon
        block["_seasonal_period"] = block["target_period"] - 12
        block = block.merge(seasonal, on=[series_col, "_seasonal_period"], how="left")
        block["calendar_month"] = block["target_period"].mod(12).add(1).astype("int64")
        rows.append(block)

    frame = pd.concat(rows, ignore_index=True)
    if statics is not None:
        frame = frame.merge(statics, on=series_col, how="left")
    frame = frame.rename(columns={period_col: "origin_period"})
    frame = frame.drop(columns=["_seasonal_period"], errors="ignore")
    return frame.sort_values([series_col, "horizon"], kind="mergesort").reset_index(drop=True)


def _assert_gapless(
    frame: pd.DataFrame, *, series_col: str, period_col: str
) -> None:
    """A gap would make `shift` count observations instead of months."""
    grouped = frame.groupby(series_col, sort=False, observed=True)[period_col]
    step = grouped.diff().dropna()
    if not step.empty and (step != 1).any():
        offenders = frame.loc[step[step != 1].index, series_col].unique()[:5]
        raise ValueError(
            "The panel has period gaps, so lag features would count observations "
            f"rather than months. First offending series: {list(offenders)}. Build "
            "the panel with an explicit period grid."
        )
