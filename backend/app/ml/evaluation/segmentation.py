"""Per-series demand classification, for pooling residuals.

Phase 6 needs a segment label because quantile calibration pools residuals by
**model x horizon x demand segment** (`docs/MODEL_INVENTORY.md` §3): one origin
times six validation months yields six residuals per series, far too few to
calibrate an interval per series, so residuals are pooled - but pooling a
smooth high-volume series with an intermittent one would produce an interval
honest about neither.

The classification is Syntetos-Boylan, on the standard cutoffs:

| | CV² < 0.49 | CV² >= 0.49 |
|---|---|---|
| **ADI < 1.32** | `smooth` | `erratic` |
| **ADI >= 1.32** | `intermittent` | `lumpy` |

Two extra labels exist because the textbook four do not cover AIS's data:

- `no_demand` - every observed month is zero. ADI is undefined (division by
  zero non-zero months), not infinite.
- `single_event` - exactly one non-zero month. CV² needs two non-zero
  observations, so it is undefined; calling such a series `intermittent` would
  imply a measured dispersion that was never measured.

Both are reported as themselves. Neither is folded into the nearest textbook
class, and neither is dropped: on this dataset they are a large minority, and a
segment that quietly disappears is how a leaderboard ends up describing a
different population than the one it forecast.

This module is grain- and dataset-agnostic: it takes a target series and
returns a label. It contains no AIS column names, per the boundary rule in
CLAUDE.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Sequence

import numpy as np
import pandas as pd

#: Syntetos-Boylan cutoffs. The literature's values, not tuned here.
ADI_CUTOFF = 1.32
CV_SQUARED_CUTOFF = 0.49


class DemandSegment(StrEnum):
    SMOOTH = "smooth"
    ERRATIC = "erratic"
    INTERMITTENT = "intermittent"
    LUMPY = "lumpy"
    NO_DEMAND = "no_demand"
    SINGLE_EVENT = "single_event"


@dataclass(frozen=True)
class SeriesProfile:
    """One series' sparsity, and the segment those numbers imply."""

    observed_months: int
    nonzero_months: int
    adi: float | None
    cv_squared: float | None
    segment: DemandSegment

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_months": self.observed_months,
            "nonzero_months": self.nonzero_months,
            "adi": self.adi,
            "cv_squared": self.cv_squared,
            "segment": self.segment.value,
        }


def profile_series(target: Sequence[Any]) -> SeriesProfile:
    """ADI, CV² and the Syntetos-Boylan segment for one series.

    ADI is months per non-zero month; CV² is the squared coefficient of
    variation of the **non-zero** values, which is the Syntetos-Boylan
    definition - taking it over all months instead would let the zeros inflate
    the dispersion and reclassify most of the panel as lumpy.
    """
    values = pd.to_numeric(pd.Series(list(target)), errors="coerce").dropna().astype(float)
    observed = int(len(values))
    nonzero = values[values != 0]
    nonzero_count = int(len(nonzero))

    if observed == 0 or nonzero_count == 0:
        return SeriesProfile(observed, nonzero_count, None, None, DemandSegment.NO_DEMAND)

    adi = observed / nonzero_count
    if nonzero_count < 2:
        return SeriesProfile(
            observed, nonzero_count, adi, None, DemandSegment.SINGLE_EVENT
        )

    mean = float(nonzero.mean())
    if mean == 0:
        return SeriesProfile(observed, nonzero_count, adi, None, DemandSegment.SINGLE_EVENT)
    cv_squared = float((nonzero.std(ddof=0) / mean) ** 2)

    intermittent = adi >= ADI_CUTOFF
    variable = cv_squared >= CV_SQUARED_CUTOFF
    if intermittent and variable:
        segment = DemandSegment.LUMPY
    elif intermittent:
        segment = DemandSegment.INTERMITTENT
    elif variable:
        segment = DemandSegment.ERRATIC
    else:
        segment = DemandSegment.SMOOTH
    return SeriesProfile(observed, nonzero_count, adi, cv_squared, segment)


def profile_panel(
    panel: pd.DataFrame,
    *,
    series_col: str = "series_id",
    target_col: str = "target",
) -> pd.DataFrame:
    """One row per series: observed months, non-zero months, ADI, CV², segment.

    Vectorised rather than a `groupby.apply` of `profile_series`, because at
    68,675 series the per-group Python call dominates. `profile_series` remains
    the definition and `tests/test_metrics.py` asserts the two agree.
    """
    if panel.empty:
        return pd.DataFrame(
            columns=[series_col, "observed_months", "nonzero_months", "adi", "cv_squared", "segment"]
        )

    frame = panel[[series_col, target_col]].copy()
    frame[target_col] = pd.to_numeric(frame[target_col], errors="coerce")
    frame = frame.dropna(subset=[target_col])

    observed = frame.groupby(series_col, sort=False, observed=True)[target_col].size()
    nonzero_frame = frame[frame[target_col] != 0]
    grouped_nonzero = nonzero_frame.groupby(series_col, sort=False, observed=True)[target_col]
    nonzero_count = grouped_nonzero.size().reindex(observed.index, fill_value=0)
    nonzero_mean = grouped_nonzero.mean().reindex(observed.index)
    nonzero_std = grouped_nonzero.std(ddof=0).reindex(observed.index)

    adi = pd.Series(np.nan, index=observed.index, dtype=float)
    has_demand = nonzero_count > 0
    adi[has_demand] = observed[has_demand] / nonzero_count[has_demand]

    cv_squared = pd.Series(np.nan, index=observed.index, dtype=float)
    computable = (nonzero_count >= 2) & nonzero_mean.notna() & (nonzero_mean != 0)
    cv_squared[computable] = (nonzero_std[computable] / nonzero_mean[computable]) ** 2

    segment = pd.Series(DemandSegment.NO_DEMAND.value, index=observed.index, dtype=object)
    segment[has_demand & ~computable] = DemandSegment.SINGLE_EVENT.value
    intermittent = adi >= ADI_CUTOFF
    variable = cv_squared >= CV_SQUARED_CUTOFF
    segment[computable & intermittent & variable] = DemandSegment.LUMPY.value
    segment[computable & intermittent & ~variable] = DemandSegment.INTERMITTENT.value
    segment[computable & ~intermittent & variable] = DemandSegment.ERRATIC.value
    segment[computable & ~intermittent & ~variable] = DemandSegment.SMOOTH.value

    return pd.DataFrame(
        {
            series_col: observed.index,
            "observed_months": observed.to_numpy(),
            "nonzero_months": nonzero_count.to_numpy(),
            "adi": adi.to_numpy(),
            "cv_squared": cv_squared.to_numpy(),
            "segment": segment.to_numpy(),
        }
    ).reset_index(drop=True)


def segment_counts(profiles: pd.DataFrame) -> dict[str, int]:
    """Segment histogram, with every label present even at zero.

    A missing key and a zero are different facts, and a caller reading a
    histogram should not have to know which segments exist to tell them apart.
    """
    counts = profiles["segment"].value_counts().to_dict() if len(profiles) else {}
    return {segment.value: int(counts.get(segment.value, 0)) for segment in DemandSegment}
