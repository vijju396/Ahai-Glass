"""How accurate the same forecasts are, judged over different planning windows.

The leaderboard reports one number: how wrong a model was on an average single
month of a single branch x SKU. On this workspace that is about 76% accurate,
and no amount of model work moves it much, because the thing being measured
will not sit still - the median line here swings 43% from one month to the
next, and a constant chosen *knowing the answers in advance* only reaches 69%.

But "how wrong on one SKU in one month" is not the only question a plant asks,
and it is usually not the one it acts on. A schedule covering a quarter is
judged on the quarter's total; a furnace load is judged on the branch total.
Those are the same forecasts, added up differently, and they are measurably
more accurate - because the misses are in both directions and cancel.

So this module re-scores the champions' stored backtest predictions over each
window, and reports the honest figure for each. Nothing is re-fitted and no
metric is redefined: every number is the same absolute percentage error, over a
different total.

**It does not make the monthly number better, and does not claim to.** The
monthly row is reported first and unchanged, so a reader cannot come away
thinking a window changed the forecast rather than the question.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.champions import ChampionSelection
from app.models.training import ModelRun

#: Windows reported, as a count of consecutive forecast months summed together.
#: 1 is the leaderboard's own question, kept first so it cannot be lost.
WINDOWS: tuple[int, ...] = (1, 3, 6)

#: The accuracy a plan is usually held to. Reported as a count of windows that
#: reach it, never as an average dressed up to clear it.
TARGET_ACCURACY = 85.0


@dataclass
class WindowScore:
    """One way of asking the question, and what it measures.

    Two counts are kept, because they answer different questions and the
    difference between them is the whole point of the panel:

    - ``blocks`` — every scored stretch, pooled. Its median is the headline.
    - ``by_series`` — the same stretches kept apart by branch x SKU, so the
      panel can say **how many lines clear the target on their own**. A pooled
      median of 86% with half the lines under 85% is not "86% accurate", and
      reporting only the pooled figure would say it was.
    """

    label: str
    months: int
    level: str
    blocks: list[float] = field(default_factory=list)
    by_series: dict[str, list[float]] = field(default_factory=dict)
    #: Running totals for a volume-weighted (WAPE) reading: the summed absolute
    #: error and the summed actual across every block. A big-selling line then
    #: counts for more than a slow one, which the median across lines does not.
    abs_error_total: float = 0.0
    actual_total: float = 0.0

    def add(
        self,
        scope_key: str,
        error_pct: float,
        abs_error: float = 0.0,
        actual: float = 0.0,
    ) -> None:
        self.blocks.append(error_pct)
        self.by_series.setdefault(scope_key, []).append(error_pct)
        self.abs_error_total += abs_error
        self.actual_total += actual

    def pooled_wape(self) -> float | None:
        """Summed absolute error as a share of summed actual, across the
        window. None when nothing was scored."""
        if not self.actual_total:
            return None
        return self.abs_error_total / self.actual_total * 100

    def series_accuracy(self) -> dict[str, float]:
        """Each line's own accuracy over this window."""
        return {
            key: max(0.0, 100.0 - statistics.median(values))
            for key, values in self.by_series.items()
            if values
        }

    def as_dict(self) -> dict[str, Any]:
        lines = self.series_accuracy()
        clear = sum(1 for value in lines.values() if value >= TARGET_ACCURACY)
        if not self.blocks:
            return {
                "label": self.label,
                "months": self.months,
                "level": self.level,
                "blocks": 0,
                "median_error_pct": None,
                "accuracy_pct": None,
                "blocks_at_target": 0,
                "share_at_target_pct": None,
                "meets_target": False,
                "series_scored": 0,
                "series_at_target": 0,
                "worst_series_accuracy_pct": None,
            }
        median = statistics.median(self.blocks)
        hit = sum(1 for value in self.blocks if value <= 100 - TARGET_ACCURACY)
        return {
            "label": self.label,
            "months": self.months,
            "level": self.level,
            "blocks": len(self.blocks),
            "median_error_pct": round(median, 2),
            "accuracy_pct": round(max(0.0, 100.0 - median), 2),
            "blocks_at_target": hit,
            "share_at_target_pct": round(hit / len(self.blocks) * 100, 1),
            "meets_target": bool(100.0 - median >= TARGET_ACCURACY),
            "series_scored": len(lines),
            "series_at_target": clear,
            "worst_series_accuracy_pct": (
                round(min(lines.values()), 2) if lines else None
            ),
        }


def _origin_blocks(run: ModelRun) -> list[tuple[list[float], list[float]]]:
    """Each origin's (actuals, predictions), ordered by horizon.

    An origin missing either side, or scoring fewer months than it forecast, is
    dropped rather than padded: a window summed over a hole is not that window.
    """
    blocks: list[tuple[list[float], list[float]]] = []
    for origin in run.origins_json or []:
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


def _add_window(
    score: WindowScore,
    scope_key: str,
    actuals: Sequence[float],
    predicted: Sequence[float],
) -> None:
    """Score every complete `score.months` block inside one origin."""
    step = score.months
    for start in range(0, len(actuals) - step + 1, step):
        total_actual = sum(actuals[start : start + step])
        total_predicted = sum(predicted[start : start + step])
        if not total_actual:
            # No denominator. Reported nowhere rather than counted as perfect
            # or as a total miss; both would be inventions.
            continue
        score.add(
            scope_key,
            abs(total_predicted - total_actual) / abs(total_actual) * 100,
            abs_error=abs(total_predicted - total_actual),
            actual=abs(total_actual),
        )


def accuracy_by_window(
    db: Session, run_id: str, scope_key: str | None = None
) -> dict[str, Any]:
    """Every champion's backtest, re-scored over each planning window.

    With ``scope_key`` the answer narrows to one branch x SKU line. That is the
    only way to answer the question the pooled figure cannot: *does this line
    clear the target*, rather than *does the middle line clear it*.
    """
    filters = [
        ChampionSelection.training_run_id == run_id,
        ChampionSelection.is_active.is_(True),
        ChampionSelection.scope_kind == "series",
    ]
    if scope_key:
        filters.append(ChampionSelection.scope_key == scope_key)
    selections = list(db.scalars(select(ChampionSelection).where(*filters)))
    runs = {
        row.id: row
        for row in db.scalars(
            select(ModelRun).where(ModelRun.training_run_id == run_id)
        )
    }

    scores = [
        WindowScore(
            label={
                1: "One month at a time",
                3: "A 3-month total",
                6: "A 6-month total",
            }[months],
            months=months,
            level="series",
        )
        for months in WINDOWS
    ]
    # The whole workspace in one month: every SKU's forecast added together and
    # compared against every SKU's actual. This is what a furnace load is
    # judged on, and it is the same predictions again. Meaningless once the
    # view is narrowed to a single line - there it would restate the first row
    # under a name that implies more evidence - so it is only built for the
    # unfiltered view.
    together = WindowScore(label="Every SKU added together, one month", months=1, level="all_series")
    pooled: dict[tuple[int, int], list[float]] = {}

    covered = 0
    champions: dict[str, str] = {}
    # The combined metrics shown as tiles are the champions' own official,
    # leakage-safe MAPE and WAPE, aggregated across lines. Pooling raw backtest
    # points instead would let a single blown-up or negative forecast (a model
    # extrapolating below zero on a thin line) swamp the aggregate, which is
    # exactly why the per-line metric is the median, not a pooled sum.
    line_metrics: dict[str, tuple[float | None, float | None]] = {}
    for selection in selections:
        run = runs.get(selection.champion_model_run_id or "")
        if run is None:
            continue
        origin_blocks = _origin_blocks(run)
        if not origin_blocks:
            continue
        covered += 1
        key = str(selection.scope_key)
        champions[key] = str(selection.champion_model_id)
        line_metrics[key] = (
            float(run.mape) if run.mape is not None else None,
            float(run.wape) if run.wape is not None else None,
        )
        for origin_index, (actuals, predicted) in enumerate(origin_blocks):
            for score in scores:
                _add_window(score, key, actuals, predicted)
            for horizon_index, (actual, prediction) in enumerate(zip(actuals, predicted)):
                cell = pooled.setdefault((origin_index, horizon_index), [0.0, 0.0])
                cell[0] += prediction
                cell[1] += actual

    if not scope_key:
        for prediction_total, actual_total in pooled.values():
            if actual_total:
                together.add(
                    "all_series",
                    abs(prediction_total - actual_total) / abs(actual_total) * 100,
                )

    def _combine(keys: list[str]) -> dict[str, Any]:
        """Median across the given lines of each line's own champion metric.

        Accuracy is the median of each line's clamped accuracy, not
        100 - median(MAPE): a line whose MAPE exceeds 100 floors at 0
        accuracy, and averaging the floored values is the honest summary. A
        pooled sum would let one blown-up forecast swamp the aggregate, which
        is why every figure here is a per-line median."""
        mapes = [
            line_metrics[k][0]
            for k in keys
            if line_metrics.get(k, (None, None))[0] is not None
        ]
        wapes = [
            line_metrics[k][1]
            for k in keys
            if line_metrics.get(k, (None, None))[1] is not None
        ]

        def med(values: list[float]) -> float | None:
            return round(statistics.median(values), 2) if values else None

        return {
            "accuracy_pct": med([max(0.0, 100.0 - m) for m in mapes]),
            "mape_pct": med(mapes),
            "wape_pct": med(wapes),
            "weighted_accuracy_pct": med([max(0.0, 100.0 - w) for w in wapes]),
            "lines": len(mapes),
        }

    combined_metrics = _combine(list(line_metrics.keys()))

    rows = [score.as_dict() for score in scores]
    if not scope_key:
        rows.append(together.as_dict())
    # The recommended window is the *shortest* that clears the target, because
    # a wider window is a vaguer promise and there is no reason to give up
    # detail that is already accurate enough.
    best = next((row for row in rows if row["meets_target"]), None)

    # Per-line accuracy at each window, so the panel can name the lines that do
    # not clear the target instead of averaging them away.
    per_series = [
        {
            "scope_key": key,
            "champion_model_id": champions.get(key),
            "accuracy_pct": {
                str(score.months): round(score.series_accuracy().get(key), 2)
                for score in scores
                if score.series_accuracy().get(key) is not None
            },
            # The champion's own accuracy, 100 - MAPE, on the average month.
            # This is the figure the leaderboard and the training console show
            # for this line, and it is a different measurement from any window
            # accuracy above: a six-month total lets an over-forecast month
            # cancel an under-forecast one, and the average month does not.
            # A line can read 89.9% over six months and 84.2% on the average
            # month, and both are true.
            "champion_accuracy_pct": (
                round(max(0.0, 100.0 - line_metrics[key][0]), 2)
                if line_metrics.get(key, (None, None))[0] is not None
                else None
            ),
        }
        for key in sorted(champions)
    ]
    for row in per_series:
        best_window = row["accuracy_pct"].get(str(best["months"])) if best else None
        row["meets_target"] = bool(
            best_window is not None and best_window >= TARGET_ACCURACY
        )
        # Whether the number a viewer will actually see for this line clears
        # the target. The filters mark lines on this, not on `meets_target`:
        # marking on the window figure put a dot on fifteen lines whose console
        # reading was below 85% - one at 48.8% - because the two measure
        # different things. A mark has to predict what the next screen says.
        row["champion_meets_target"] = bool(
            row["champion_accuracy_pct"] is not None
            and row["champion_accuracy_pct"] >= TARGET_ACCURACY
        )
    below = [row for row in per_series if not row["meets_target"]]

    # The headline figures for the demo, measured at the recommended window -
    # the six-month total, where a plan is actually held. Accuracy is the
    # median line's accuracy over that window (half the lines do better, half
    # worse - it is a median, not a promise every line clears), and the
    # volume-weighted pair counts a big-selling line for more than a slow one.
    # This is the "86%" figure, kept honest by the per-line green marks and the
    # count of lines that clear the target on their own.
    best_score = next(
        (s for s in scores if best is not None and s.months == best["months"]),
        None,
    )
    if best_score is not None:
        best_dict = best_score.as_dict()
        best_wape = best_score.pooled_wape()
        combined_metrics_best = {
            "accuracy_pct": best_dict["accuracy_pct"],
            "mape_pct": best_dict["median_error_pct"],
            "wape_pct": round(best_wape, 2) if best_wape is not None else None,
            "weighted_accuracy_pct": (
                round(max(0.0, 100.0 - best_wape), 2) if best_wape is not None else None
            ),
            "lines": best_dict["series_scored"],
            "window_label": best_dict["label"],
            "window_months": best_dict["months"],
        }
    else:
        combined_metrics_best = None

    return {
        "training_run_id": run_id,
        "scope_key": scope_key,
        "target_accuracy_pct": TARGET_ACCURACY,
        "series_covered": covered,
        "series_with_champion": len(selections),
        "combined_metrics": combined_metrics,
        "combined_metrics_best": combined_metrics_best,
        "windows": rows,
        "meets_target_at": best["label"] if best else None,
        "recommended_months": best["months"] if best else None,
        "series": per_series,
        "series_below_target": len(below),
        "notes": [
            "Every row is the same forecasts and the same measurement - the "
            "absolute percentage error - over a different total. Nothing is "
            "re-fitted and no metric is redefined.",
            (
                "These figures are the MIDDLE month, and the leaderboard's "
                "MAPE is the AVERAGE month. They differ, sometimes hugely, and "
                "both are correct. On a line trading a few units, one month "
                "forecast 8 against an actual of 1 is a 669% error that drags "
                "an average past 100% while leaving the middle month alone. "
                "The middle is used here because a planning window is judged "
                "by its typical outcome; the average is kept on the "
                "leaderboard because it is what punishes a model for a "
                "blow-up. Read a disagreement between them as a warning that "
                "the line has at least one very bad month."
            ),
            (
                f"A {TARGET_ACCURACY:.0f}% target is reached at "
                f"'{best['label']}'."
                if best
                else f"No window on this run reaches {TARGET_ACCURACY:.0f}%."
            ),
            (
                "The headline is a middle line, not a floor. "
                f"{best['series_at_target']} of {best['series_scored']} lines "
                f"clear {TARGET_ACCURACY:.0f}% on their own at that window"
                if best
                else "No window clears the target, so no line count is quoted"
            )
            + ". Filter to a line to see its own figure.",
            (
                "Monthly accuracy per SKU is set by how much the SKU itself "
                "moves, not by the choice of model. Where a line swings by "
                "more than the target allows, no model can clear the target on "
                "it, and a longer planning window is the honest way to a "
                "figure that can be planned against - not a better fit."
            ),
        ],
    }
