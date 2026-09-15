"""Non-registry baselines: naive, seasonal naive, MA3, MA6.

These are **not** among the 13. They exist for two jobs:

1. To be reported next to the leaderboard, so a model that cannot beat "repeat
   last month" is visibly not worth deploying.
2. As the MASE denominator - though note that MASE's denominator is the
   *in-sample* one-step naive error computed in `metrics._mase`, which is a
   different quantity from the out-of-sample naive forecast produced here.

`canonical_models.assert_canonical_registry()` fails if any of these ids ever
appears among the 13, and no baseline can be champion. The ids come from
`BASELINE_METHOD_IDS` rather than being re-listed here, so there is one source
of truth for what is and is not a registered model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from app.ml.registry.canonical_models import BASELINE_DISPLAY_NAMES, BASELINE_METHOD_IDS


@dataclass
class BaselineForecast:
    """A baseline's forecast, plus what it fell back to and why.

    `fallback_reason` is populated whenever the method could not be applied as
    named - a seasonal naive without a full cycle of history, say. Reporting a
    silent fallback as if it were the requested method would make the baseline
    comparison meaningless, since the interesting case is exactly the series
    with too little history.
    """

    method_id: str
    display_name: str
    values: list[float]
    applied_method: str
    fallback_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "display_name": self.display_name,
            "values": list(self.values),
            "applied_method": self.applied_method,
            "fallback_reason": self.fallback_reason,
        }


def forecast_baseline(
    method_id: str,
    history: Sequence[Any],
    horizon: int,
    *,
    seasonal_period: int | None = None,
) -> BaselineForecast:
    """Forecast `horizon` steps from `history` using one baseline method.

    `history` is the training window only. Every method here is a flat or
    cyclic extrapolation of it, so none can leak: there is nothing in the
    computation that could reach past the origin even by accident.
    """
    if method_id not in BASELINE_METHOD_IDS:
        raise ValueError(
            f"{method_id!r} is not a baseline method. Valid ids: "
            f"{list(BASELINE_METHOD_IDS)}. The 13 registered models are reached "
            "through MODEL_REGISTRY, not through this function."
        )
    display_name = BASELINE_DISPLAY_NAMES[method_id]
    values = _usable(history)

    if not len(values):
        return BaselineForecast(
            method_id=method_id,
            display_name=display_name,
            values=[math.nan] * horizon,
            applied_method="none",
            fallback_reason=(
                "the training window holds no usable observation, so no baseline "
                "is defined; the row reports no forecast rather than zero"
            ),
        )

    if method_id == "naive":
        return BaselineForecast(
            method_id, display_name, [float(values[-1])] * horizon, "naive"
        )

    if method_id == "seasonal_naive":
        return _seasonal_naive(method_id, display_name, values, horizon, seasonal_period)

    window = 3 if method_id == "ma3" else 6
    if len(values) < window:
        mean = float(values.mean())
        return BaselineForecast(
            method_id,
            display_name,
            [mean] * horizon,
            applied_method=f"ma{len(values)}",
            fallback_reason=(
                f"only {len(values)} observations available for a {window}-month "
                f"mean, so the mean of all {len(values)} was used"
            ),
        )
    mean = float(values[-window:].mean())
    return BaselineForecast(method_id, display_name, [mean] * horizon, f"ma{window}")


def _seasonal_naive(
    method_id: str,
    display_name: str,
    values: np.ndarray,
    horizon: int,
    seasonal_period: int | None,
) -> BaselineForecast:
    """Repeat the last complete cycle, or say why it could not.

    Falls back to plain naive rather than to zero. A fallback to zero would
    look like a confident forecast of no demand, which is a different and much
    more damaging claim than "this series has too little history for a seasonal
    method".
    """
    if not seasonal_period or seasonal_period < 1:
        return BaselineForecast(
            method_id,
            display_name,
            [float(values[-1])] * horizon,
            applied_method="naive",
            fallback_reason=(
                "no seasonal period was resolved for this series, so the seasonal "
                "naive degenerates to naive"
            ),
        )
    if len(values) < seasonal_period:
        return BaselineForecast(
            method_id,
            display_name,
            [float(values[-1])] * horizon,
            applied_method="naive",
            fallback_reason=(
                f"a period of {seasonal_period} needs {seasonal_period} months of "
                f"history and only {len(values)} are available, so the seasonal "
                "naive degenerates to naive"
            ),
        )
    cycle = values[-seasonal_period:]
    return BaselineForecast(
        method_id,
        display_name,
        [float(cycle[step % seasonal_period]) for step in range(horizon)],
        f"seasonal_naive_{seasonal_period}",
    )


def forecast_all_baselines(
    history: Sequence[Any],
    horizon: int,
    *,
    seasonal_period: int | None = None,
) -> dict[str, BaselineForecast]:
    """Every baseline, keyed by method id, in registry order."""
    return {
        method_id: forecast_baseline(
            method_id, history, horizon, seasonal_period=seasonal_period
        )
        for method_id in BASELINE_METHOD_IDS
    }


def _usable(history: Sequence[Any]) -> np.ndarray:
    kept: list[float] = []
    for value in history:
        try:
            as_float = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(as_float) or math.isinf(as_float):
            continue
        kept.append(as_float)
    return np.asarray(kept, dtype=float)
