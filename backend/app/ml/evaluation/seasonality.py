"""Seasonal-period resolution.

Ported from Sodexo's `validation_plan.resolve_seasonal_period`
(`validation_plan.py:56-77`), which itself ports Meriton's `_seasonal_period`:
pick whichever candidate cycle has the stronger autocorrelation, requiring two
complete cycles of history in the **smallest fold** a rolling-origin CV will
actually fit on - not merely in the full window. A period that fits the full
series but not an individual fold makes every fold's fit fail at runtime.

**Why more than one candidate matters for AIS.** At monthly grain the natural
period is 12, which needs 24 observations for two cycles. The panel offers at
most 22 training months before a six-month holdout, so 12 can never be
satisfied and all four Exponential Smoothing variants are permanently
Ineligible under the reference profile.

That is the honest answer, and it is the default. The `monthly_relaxed`
profile - the documented opt-in of docs/DECISIONS.md D-001 - additionally
considers shorter cycles (6, then 4, then 3), so those four models become
genuinely evaluable instead of being written off. A half-year cycle is a real
pattern in replacement demand, not a fiction invented to fill a leaderboard,
but it is a weaker claim than an annual one and the profile label says so.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.ml.evaluation.folds import smallest_fold_train_size
from app.ml.features.grain import MONTHLY, PERIODS_PER_YEAR, WEEKLY

#: The annual cycle at monthly grain. Kept as a module constant because callers
#: and tests name it directly; `annual_period(grain)` is the grain-aware form.
ANNUAL_PERIOD = PERIODS_PER_YEAR[MONTHLY]


def annual_period(grain: str = MONTHLY) -> int:
    """The annual cycle in periods: 12 monthly, 52 weekly."""
    return PERIODS_PER_YEAR[grain]


#: Candidates per history profile, strongest first, per grain. The relaxed
#: profile keeps the annual cycle at the front so a series with enough history
#: still gets it, then steps down through half-year, quarter and month.
#:
#: **Weekly does not rescue the annual cycle.** 52 needs 104 observations for
#: two complete cycles and the weekly panel offers 78 at the primary origin and
#: 96 at the second, so the reference profile still resolves to `None` and the
#: four Exponential Smoothing variants stay Ineligible - the same honest answer
#: monthly gave, for the same reason. What weekly does change is the relaxed
#: profile: 26, 13 and 4 all clear their two-cycle floor with room to spare,
#: where monthly's 6, 4 and 3 were scraping against an 18-period fold (D-107).
_CANDIDATES_BY_GRAIN: dict[str, dict[str, tuple[int, ...]]] = {
    MONTHLY: {
        "reference": (12,),
        "monthly_relaxed": (12, 6, 4, 3),
    },
    WEEKLY: {
        "reference": (52,),
        "monthly_relaxed": (52, 26, 13, 4),
    },
}

#: Monthly candidates, under the name callers already import.
SEASONAL_CANDIDATES: dict[str, tuple[int, ...]] = _CANDIDATES_BY_GRAIN[MONTHLY]


def seasonal_candidates(profile: str, grain: str = MONTHLY) -> tuple[int, ...]:
    """Candidate cycles for a profile at a grain, strongest first."""
    by_profile = _CANDIDATES_BY_GRAIN[grain]
    return by_profile.get(profile, by_profile["reference"])


@dataclass
class SeasonalResolution:
    period: int | None
    strength: float | None
    candidates_considered: tuple[int, ...]
    rejected: dict[int, str]
    reference_length: int
    profile: str

    def as_dict(self) -> dict[str, object]:
        return {
            "period": self.period,
            "autocorrelation_strength": self.strength,
            "candidates_considered": list(self.candidates_considered),
            "rejected": {str(k): v for k, v in self.rejected.items()},
            "reference_length": self.reference_length,
            "profile": self.profile,
        }


def resolve_seasonal_period(
    target: pd.Series,
    *,
    profile: str = "reference",
    reference_length: int | None = None,
    grain: str = MONTHLY,
) -> SeasonalResolution:
    """The seasonal period to use, and why the others were rejected.

    `reference_length` is the history a *fold* will actually see. Pass the
    smallest fold's training size, not the full window, or a period that only
    fits the full series will fail inside every fold.

    Returns `period=None` when no candidate qualifies. That is a real answer,
    not a failure: it makes the seasonal models Ineligible with a stated reason
    rather than fitting them on a period they cannot support.
    """
    values = pd.to_numeric(target, errors="coerce").dropna().astype(float)
    length = reference_length if reference_length is not None else len(values)
    candidates = seasonal_candidates(profile, grain)

    rejected: dict[int, str] = {}
    best_period: int | None = None
    best_strength = -1.0

    for period in candidates:
        if length < period * 2:
            rejected[period] = (
                f"needs {period * 2} observations for two complete cycles, "
                f"reference window has {length}"
            )
            continue
        strength = _autocorrelation(values, period)
        if strength is None:
            rejected[period] = "autocorrelation is undefined on this series"
            continue
        if strength > best_strength:
            best_strength = strength
            best_period = period

    return SeasonalResolution(
        period=best_period,
        strength=None if best_period is None else best_strength,
        candidates_considered=candidates,
        rejected=rejected,
        reference_length=length,
        profile=profile,
    )


def _autocorrelation(values: pd.Series, lag: int) -> float | None:
    """Absolute autocorrelation at `lag`, or None when undefined.

    A constant series has zero variance, so the correlation is undefined rather
    than zero - and returning 0 would let it win a tie against a real signal.
    """
    if len(values) <= lag:
        return None
    if values.nunique() <= 1:
        return None
    with np.errstate(invalid="ignore", divide="ignore"):
        result = values.autocorr(lag=lag)
    if result is None or np.isnan(result):
        return None
    return float(abs(result))


#: Re-exported, not redefined. Fold arithmetic lives in `folds.py`; keeping a
#: second copy here is exactly the drift D-036 was about. Existing callers and
#: tests import it from this module, so the name stays available.
__all__ = ["ANNUAL_PERIOD", "SEASONAL_CANDIDATES", "annual_period", "seasonal_candidates", "SeasonalResolution",
           "resolve_seasonal_period", "smallest_fold_train_size"]
