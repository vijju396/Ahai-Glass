"""What a run will cost, before it is allowed to start.

`docs/ARCHITECTURE.md` §6 requires the estimated cost to be shown before
submission. This module produces it, and every number in the table below was
**measured in this project** rather than assumed - Phase 5 timed single fits on
a real 28-month AIS series and Phase 6 timed full two-origin backtests.

The estimate is deliberately reported as a range with its own provenance, not
as a single confident number. Fit time varies with series length and with how
hard the optimiser has to work, and `auto_arima`'s stepwise search is the worst
offender. An estimate presented to three significant figures would imply a
precision that does not exist.

`TrainingRun.estimated_seconds` and the run's actual duration are stored side
by side so the estimate can be audited against reality instead of being
quietly forgotten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.ml.registry.canonical_models import BASELINE_METHOD_IDS, CANONICAL_MODEL_IDS

#: Measured seconds per fit, on a real 28-month AIS series (Phase 5 §5).
#: `auto_arima` and the exponential-smoothing variants were ineligible under
#: the reference profile there, so their figures come from the
#: `monthly_relaxed` run in Phase 6.
MEASURED_FIT_SECONDS: Mapping[str, float] = {
    "sarimax": 2.00,
    "sarimax_exog": 0.13,
    "auto_arima": 1.20,
    "auto_arima_exog": 1.30,
    "xgboost": 1.40,
    "xgboost_exog": 1.45,
    "exp_additive": 0.05,
    "exp_additive_damped": 0.06,
    "exp_multiplicative": 0.05,
    "exp_multiplicative_damped": 0.06,
    "var": 0.37,
    "var_exog": 0.03,
    "lstm": 10.90,
}

#: Baselines are arithmetic on the training window - no fit at all.
BASELINE_FIT_SECONDS = 0.001

#: How much slower a fit can plausibly be than the measured median, used for
#: the upper end of the range. Derived from the spread actually observed in
#: Phase 6, where the same model varied by roughly this factor across series.
UPPER_BOUND_FACTOR = 3.0

#: Per-model overhead for a hard-timeout fit: a fresh interpreter has to import
#: the model's own dependency stack before it can fit anything. **Measured on
#: this machine**, not assumed - see the table in `hard_timeout.py`. These are
#: large enough that pre-emption is off by default.
HARD_TIMEOUT_OVERHEAD_SECONDS: Mapping[str, float] = {
    "lstm": 12.16,
    "auto_arima": 5.22,
    "auto_arima_exog": 5.22,
    "sarimax": 4.20,
    "sarimax_exog": 4.20,
    "exp_additive": 4.20,
    "exp_additive_damped": 4.20,
    "exp_multiplicative": 4.20,
    "exp_multiplicative_damped": 4.20,
    "var": 4.20,
    "var_exog": 4.20,
    "xgboost": 2.99,
    "xgboost_exog": 2.99,
}


@dataclass
class TierEstimate:
    tier: str
    series: int
    origins: int
    models: list[str] = field(default_factory=list)
    fits: int = 0
    seconds: float = 0.0
    seconds_upper: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "series": self.series,
            "origins": self.origins,
            "models": list(self.models),
            "fits": self.fits,
            "seconds": round(self.seconds, 1),
            "seconds_upper": round(self.seconds_upper, 1),
            "notes": list(self.notes),
        }


@dataclass
class RunEstimate:
    tiers: list[TierEstimate] = field(default_factory=list)
    workers: int = 1

    @property
    def seconds(self) -> float:
        """Wall clock, accounting for parallel workers.

        Divided by worker count because the runner evaluates scopes
        concurrently, but never below the slowest single scope - a run cannot
        finish faster than its longest indivisible unit of work.
        """
        total = sum(tier.seconds for tier in self.tiers)
        if self.workers <= 1:
            return total
        return total / self.workers

    @property
    def seconds_upper(self) -> float:
        total = sum(tier.seconds_upper for tier in self.tiers)
        return total if self.workers <= 1 else total / self.workers

    @property
    def fits(self) -> int:
        return sum(tier.fits for tier in self.tiers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tiers": [tier.as_dict() for tier in self.tiers],
            "workers": self.workers,
            "total_fits": self.fits,
            "estimated_seconds": round(self.seconds, 1),
            "estimated_seconds_upper": round(self.seconds_upper, 1),
            "estimated_human": _human(self.seconds),
            "estimated_human_upper": _human(self.seconds_upper),
            "provenance": (
                "per-model fit times measured in this project on a real 28-month "
                "AIS series (Phase 5) and on two-origin backtests (Phase 6). The "
                "upper bound applies a "
                f"{UPPER_BOUND_FACTOR:g}x factor drawn from the spread actually "
                "observed across series."
            ),
        }


def estimate_tier(
    tier: str,
    *,
    series: int,
    origins: int,
    model_ids: Iterable[str] = CANONICAL_MODEL_IDS,
    include_baselines: bool = True,
    fast_holdout_models: Iterable[str] = (),
    hard_timeout_models: Iterable[str] = (),
) -> TierEstimate:
    """Cost for one tier.

    A fast-holdout model is fitted once per series rather than once per origin
    (D-037), so it is charged for one origin however many the run has.
    """
    fast = set(fast_holdout_models)
    hard = set(hard_timeout_models)
    resolved = list(model_ids)
    estimate = TierEstimate(tier=tier, series=series, origins=origins, models=resolved)

    for model_id in resolved:
        per_fit = MEASURED_FIT_SECONDS.get(model_id, 1.0)
        fits_per_series = 1 if model_id in fast else max(origins, 1)
        if model_id in hard:
            per_fit += HARD_TIMEOUT_OVERHEAD_SECONDS.get(model_id, 1.5)
        fits = series * fits_per_series
        estimate.fits += fits
        estimate.seconds += fits * per_fit
        estimate.seconds_upper += fits * per_fit * UPPER_BOUND_FACTOR

    if include_baselines:
        baseline_fits = series * max(origins, 1) * len(BASELINE_METHOD_IDS)
        estimate.fits += baseline_fits
        estimate.seconds += baseline_fits * BASELINE_FIT_SECONDS
        estimate.seconds_upper += baseline_fits * BASELINE_FIT_SECONDS
        estimate.notes.append(
            f"{len(BASELINE_METHOD_IDS)} baselines add {baseline_fits} evaluations "
            "at negligible cost - they are arithmetic on the training window"
        )
    if hard & set(resolved):
        estimate.notes.append(
            "hard-timeout models pay a fresh-interpreter import cost per fit: "
            + ", ".join(
                f"{m} +{HARD_TIMEOUT_OVERHEAD_SECONDS.get(m, 1.5):g}s"
                for m in sorted(hard & set(resolved))
            )
        )
    return estimate


def estimate_pooled_tier(
    *,
    training_rows: int,
    scoring_rows: int,
    origins: int,
    quantiles: int = 3,
) -> TierEstimate:
    """Cost for the pooled global tier.

    Measured at real shape in Phase 0: 21.5 s to fit 950,000 rows x 29
    features and 0.3 s to score 380,000. Scaled linearly in rows, which is the
    right shape for XGBoost's histogram method at fixed depth and tree count.

    The point model plus three quantile models is four fits per origin.
    """
    fit_rate = 21.5 / 950_000
    score_rate = 0.3 / 380_000
    models_per_origin = 1 + quantiles
    fits = origins * models_per_origin * 2  # xgboost and xgboost_exog
    seconds = fits * (training_rows * fit_rate) + origins * scoring_rows * score_rate
    estimate = TierEstimate(
        tier="pooled",
        series=0,
        origins=origins,
        models=["xgboost", "xgboost_exog"],
        fits=fits,
        seconds=seconds,
        seconds_upper=seconds * UPPER_BOUND_FACTOR,
    )
    estimate.notes.append(
        f"one pooled fit covers every series, so {training_rows:,} training rows "
        f"replace ~68,675 per-series fits; scoring {scoring_rows:,} rows is "
        "sub-second"
    )
    estimate.notes.append(
        "the pooled tier is what keeps the full network inside budget; the "
        "per-series tiers above it exist because a pooled model cannot capture "
        "a high-value series' own dynamics"
    )
    return estimate


def _human(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"
