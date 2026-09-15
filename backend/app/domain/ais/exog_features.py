"""The genuinely future-known exogenous set for AIS.

An exogenous regressor is only legitimate if its value is known for the
forecast horizon. That rules out almost everything on the panel: MRP can
change, despatched quantity has not happened, stock is a single snapshot. What
*is* knowable for any future month is the calendar, and the static attributes
that are constant per series.

So the exogenous matrix for a local per-series model is **calendar features
derived from the period index**. That is thin, and deliberately so - it is
better than the alternative, which is passing a historical driver and calling
it future-known. Mapping rule R5 blocks that at confirmation time; this module
is the positive half of the same rule.

The pooled/direct XGBoost path does not use this: its exogenous information is
already in the Phase 4 training frame as static attributes plus `horizon` and
`calendar_month`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Calendar columns derived from the period index. All future-known.
CALENDAR_EXOG_COLUMNS: tuple[str, ...] = (
    "calendar_month",
    "month_sin",
    "month_cos",
    "quarter",
)

#: Static attributes constant per series, so also future-known. Usable as
#: exogenous input only where a frame actually carries them.
STATIC_EXOG_CANDIDATES: tuple[str, ...] = (
    "region",
    "zone",
    "supply_hub",
    "tier",
    "glass_type",
    "oem_status",
    "vehicle_age_category",
)


def attach_calendar_exog(
    frame: pd.DataFrame, *, period_col: str = "period_index"
) -> pd.DataFrame:
    """Add the calendar exogenous columns, derived from the period index.

    Sine and cosine encodings are included because a raw month number tells a
    linear model that December (12) is far from January (1), when they are
    adjacent. A regression-based model needs the cyclical encoding; a tree does
    not care either way.
    """
    if period_col not in frame.columns:
        raise KeyError(
            f"{period_col!r} is required to derive calendar features; the frame "
            f"carries {list(frame.columns)[:8]}..."
        )
    result = frame.copy()
    month = result[period_col].mod(12).add(1).astype("int64")
    result["calendar_month"] = month
    radians = 2.0 * np.pi * (month - 1) / 12.0
    result["month_sin"] = np.sin(radians)
    result["month_cos"] = np.cos(radians)
    result["quarter"] = ((month - 1) // 3 + 1).astype("int64")
    return result


def resolve_exog_columns(
    frame: pd.DataFrame, *, include_static: bool = False
) -> tuple[str, ...]:
    """The future-known columns this frame actually carries.

    Returned in a deterministic order, because the exogenous rank guard keeps
    columns in the caller's order and a shuffled order would change which
    survive.
    """
    columns = [c for c in CALENDAR_EXOG_COLUMNS if c in frame.columns]
    if include_static:
        columns.extend(c for c in STATIC_EXOG_CANDIDATES if c in frame.columns)
    return tuple(columns)


def prepare_local_series_frame(
    frame: pd.DataFrame, *, period_col: str = "period_index"
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """A per-series frame ready for the local models, plus its exogenous set.

    One call so a caller cannot attach the calendar features and then forget to
    tell the adapter about them, or vice versa.
    """
    prepared = attach_calendar_exog(frame, period_col=period_col)
    return prepared, resolve_exog_columns(prepared)
