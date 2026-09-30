"""The error a model makes on the **total** it is planned against.

The leaderboard's MAPE asks "how wrong was one period of one branch x SKU".
That is not the question a plant acts on. Glass is bought on a six-month
horizon, so the number that decides a purchase is the error on the six-month
total - the same forecasts, added up before they are scored.

The two are very different, and not because one model is better than another.
Measured on run `101df724512542928d072a4698079b05`, pooled over every completed
registered model: **79.78% mean absolute percentage error per week against
26.21% on the six-month total.** Over- and under-forecasts inside a window
cancel. They do not always cancel - a model biased the same way every period
compounds instead - which is why this is measured per model rather than applied
as a correction factor.

One definition, used in three places: the training run stores it on every model
row, champion selection ranks on it, and the accuracy-windows panel reports it.
They must agree, so the blocking arithmetic lives here and nowhere else.

**What this module deliberately does not do:** it does not re-fit anything and
it does not invent a data point. An origin that scored fewer periods than it
forecast is dropped rather than padded, and a block whose actual total is zero
has no denominator and is not counted - neither as perfect nor as a total miss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


#: The planning horizon, in months. The window the champion is ranked on and
#: the widest window the accuracy panel reports are the same number by
#: construction: a leaderboard ordered on one horizon while the page reports
#: another is how the two drifted apart before (D-120).
PLANNING_HORIZON_MONTHS = 6


@dataclass(frozen=True)
class HorizonTotals:
    """What one model's stored backtest says about its totals.

    `blocks` is the honest sample size and travels with the metrics. On this
    project's two-origin plan it is 1 or 2 - so these numbers rest on one or
    two observations per model, where the per-period MAPE rests on 52. That is
    the cost of scoring the quantity a plan is held to, and it is reported
    rather than smoothed over.
    """

    #: Mean of each block's absolute percentage error. `None` when no block
    #: had a denominator.
    mape: float | None
    #: Volume-weighted: summed absolute error over summed actual, so a
    #: big-selling line is not outvoted by a slow one.
    wape: float | None
    #: How many complete blocks were scored.
    blocks: int
    #: Every block's absolute percentage error, for a caller that wants the
    #: spread rather than the middle.
    block_errors: tuple[float, ...] = ()


def origin_blocks(
    origins: Iterable[dict[str, Any]] | None,
) -> list[tuple[list[float], list[float]]]:
    """Each origin's (actuals, predictions), ordered by horizon.

    An origin missing either side, or scoring fewer periods than it forecast,
    is dropped rather than padded: a total summed over a hole is not that
    total.
    """
    blocks: list[tuple[list[float], list[float]]] = []
    for origin in origins or []:
        actuals = origin.get("actuals") or []
        predictions = origin.get("predictions") or []
        horizons = origin.get("horizons") or []
        triples = [
            (int(h), float(a), float(p))
            for h, a, p in zip(horizons, actuals, predictions)
            if a is not None and p is not None and h is not None
        ]
        if not triples:
            continue
        triples.sort()
        blocks.append(([t[1] for t in triples], [t[2] for t in triples]))
    return blocks


def block_errors(
    actuals: Sequence[float], predicted: Sequence[float], periods: int
) -> list[tuple[float, float, float]]:
    """Every complete run of `periods` inside one origin, scored on its total.

    Returns `(absolute percentage error, absolute error, absolute actual)` per
    block. The step is a count of forecast periods, not months: on a weekly
    panel a six-month window steps 26 at a time, so one origin's 26-week
    validation yields exactly one six-month block - which is the point, because
    the misses inside it are what cancel.
    """
    step = max(int(periods), 1)
    out: list[tuple[float, float, float]] = []
    for start in range(0, len(actuals) - step + 1, step):
        total_actual = sum(actuals[start : start + step])
        total_predicted = sum(predicted[start : start + step])
        if not total_actual:
            continue
        error = abs(total_predicted - total_actual)
        out.append((error / abs(total_actual) * 100, error, abs(total_actual)))
    return out


def horizon_totals(
    origins: Iterable[dict[str, Any]] | None, periods: int
) -> HorizonTotals:
    """One model row's stored backtest, scored on `periods`-long totals."""
    errors: list[float] = []
    abs_error_total = 0.0
    actual_total = 0.0
    for actuals, predicted in origin_blocks(origins):
        for ape, error, actual in block_errors(actuals, predicted, periods):
            errors.append(ape)
            abs_error_total += error
            actual_total += actual
    if not errors:
        return HorizonTotals(mape=None, wape=None, blocks=0)
    return HorizonTotals(
        mape=sum(errors) / len(errors),
        wape=(abs_error_total / actual_total * 100) if actual_total else None,
        blocks=len(errors),
        block_errors=tuple(errors),
    )
