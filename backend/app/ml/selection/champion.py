"""Champion selection: deterministic, comparability-gated, and auditable.

This module is generic. It takes rows of metrics and returns a ranking; it
knows nothing about AIS columns, and nothing about the database.

Three properties it is built around:

**Determinism.** Ranking is a total order. WAPE, then absolute bias, then MAE,
then `model_id` lexicographically (`docs/DECISIONS.md` D-011). The last key is
not decoration: two models can tie on all three metrics on a short window, and
a champion that changes between two identical runs is not a champion.

**Comparability.** A model evaluated on one origin with six test points is not
comparable to one evaluated on two origins with ten (D-037). Candidacy
therefore requires a matching `evaluation_mode` and a minimum share of the
best-observed distinct test points. A model excluded for incomparability is
**not** ranked, but it is still returned - with the reason - because hiding it
would make the leaderboard a lie by omission.

**A baseline can never be champion.** It can, and frequently does, win on WAPE
(Phase 6 measured exactly that on the median series). So the baseline's rank is
reported beside the champion's, and `beaten_by_baseline` states it plainly
rather than letting the leaderboard imply a registered model was best.

Nothing here selects a champion from a `FAILED`, `INELIGIBLE`, `TIMED_OUT` or
`NOT_EVALUATED_BUDGET` row, and nothing substitutes a metric that was `None`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Iterable, Sequence

#: The AIS operational ranking keys, in order. Documented here because the
#: order is the decision, not an implementation detail.
RANKING_KEYS: tuple[str, ...] = ("wape", "bias_abs", "mae", "model_id")

#: The legacy Meriton/Sodexo ranking: lowest valid MAPE. Kept separate and
#: separately labelled (D-011); never blended with the above.
LEGACY_RANKING_KEYS: tuple[str, ...] = ("legacy_mape", "model_id")

#: A candidate must have at least this share of the best distinct-test-point
#: count observed in its scope. 0.5 admits a `holdout_fast` model's 6 points
#: against a `rolling_origin` model's 10 within its own mode group, while still
#: excluding a row that only managed one or two points before running out of
#: history.
MIN_TEST_POINT_SHARE = 0.5

#: Below this, a metric is not evidence. One validation point can be exactly
#: right by luck.
MIN_VALIDATION_POINTS = 3

#: Metrics that may rank a scope. Both are computed for every row either way;
#: this only decides which one orders the leaderboard and picks the champion.
#:
#: **MAPE** is the default because the reported accuracy figure is
#: `100 - MAPE`, and a leaderboard ordered by one metric while the headline
#: number comes from another can put a model with the better accuracy in
#: second place. Ranking by the metric the accuracy is derived from keeps the
#: two consistent. It is also what both reference projects rank by.
#:
#: **WAPE** remains available and is still shown on every row. It is the more
#: robust choice on intermittent data, because MAPE drops zero actuals
#: entirely and divides by small ones. On the tiers AIS actually trains -
#: aggregates and the top 500 dense series - MAPE is defined for 100% of
#: completed rows, measured, so that objection does not bite here.
#:
#: The trade that does bite, and is why bias stays on every row: MAPE
#: penalises over-forecasting more than under-forecasting, so it leans toward
#: models that forecast low. Measured on this run, champions chosen by MAPE
#: under-forecast in 75% of scopes against 70% for WAPE, with a median bias of
#: -5.21% against -4.12%. For an inventory system, under-forecasting is a
#: stockout (docs/DECISIONS.md D-043).
PRIMARY_METRIC_CHOICES: tuple[str, ...] = ("mape", "wape")
DEFAULT_PRIMARY_METRIC = "mape"


class Ineligibility(StrEnum):
    """Why a row is present but unranked. Never `None`, never blank."""

    NOT_COMPLETED = "not_completed"
    NO_PRIMARY_METRIC = "no_primary_metric"
    TOO_FEW_VALIDATION_POINTS = "too_few_validation_points"
    INCOMPARABLE_TEST_WINDOW = "incomparable_test_window"
    IS_BASELINE = "is_baseline"
    NOT_DEPLOYABLE = "not_deployable"


#: Human text for each exclusion, so the API never has to invent one.
INELIGIBILITY_REASONS: dict[str, str] = {
    Ineligibility.NOT_COMPLETED: (
        "The model did not complete, so it has no metric to rank. Its status "
        "and reason are shown on the row."
    ),
    Ineligibility.NO_PRIMARY_METRIC: (
        "WAPE is undefined for this validation window - every actual in it was "
        "zero, so there is no denominator. Undefined is reported rather than "
        "substituted."
    ),
    Ineligibility.TOO_FEW_VALIDATION_POINTS: (
        f"Fewer than {MIN_VALIDATION_POINTS} validation points. A metric over "
        "one or two months is not evidence of accuracy."
    ),
    Ineligibility.INCOMPARABLE_TEST_WINDOW: (
        "Evaluated over a materially shorter validation window than the best "
        "model in this scope, so its metric is not comparable. Both point "
        "counts are shown."
    ),
    Ineligibility.IS_BASELINE: (
        "Naive, seasonal-naive, MA3 and MA6 are non-registry baselines. They "
        "are reported for comparison and can never be champion."
    ),
    Ineligibility.NOT_DEPLOYABLE: (
        "The model scored on its backtest window but cannot be fitted on this "
        "scope's full history, so it could never produce the forecast it would "
        "be crowned for. The specific requirement it fails is on the row."
    ),
}

#: Statuses that carry a usable metric. Everything else is a row that must
#: appear and must not be ranked.
_RANKABLE_STATUS = "completed"


@dataclass
class Candidate:
    """One (scope, model) row, as the ranker sees it.

    Deliberately a plain structure rather than the ORM row: the ranking rules
    are unit-testable without a database, and the same code ranks a stored run
    and a hypothetical one.
    """

    model_id: str
    display_name: str
    status: str
    is_baseline: bool = False
    evaluation_mode: str | None = None
    wape: float | None = None
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = None
    accuracy: float | None = None
    smape: float | None = None
    mase: float | None = None
    bias: float | None = None
    bias_abs: float | None = None
    legacy_mape: float | None = None
    legacy_valid: bool = False
    validation_points: int = 0
    distinct_test_points: int = 0
    origins_completed: int = 0
    origins_total: int = 0
    failure_reason: str | None = None
    model_run_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def primary(self, metric: str = DEFAULT_PRIMARY_METRIC) -> float | None:
        """The value this row is ranked on. Lower is better for both choices."""
        return self.mape if metric == "mape" else self.wape

    def sort_bias_abs(self) -> float:
        """Absolute bias, derived when it was not stored.

        Falls back to `+inf` rather than 0 so a row with no bias at all cannot
        win a tie-break against one that measured no bias.
        """
        if self.bias_abs is not None:
            return abs(self.bias_abs)
        if self.bias is not None:
            return abs(self.bias)
        return float("inf")


@dataclass
class RankedRow:
    """A candidate plus the verdict on it."""

    candidate: Candidate
    rank: int | None
    legacy_rank: int | None
    is_champion: bool
    is_challenger: bool
    ranked: bool
    exclusion: str | None
    exclusion_reason: str | None
    comparability_note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        c = self.candidate
        return {
            "model_id": c.model_id,
            "display_name": c.display_name,
            "status": c.status,
            "is_baseline": c.is_baseline,
            "evaluation_mode": c.evaluation_mode,
            "rank": self.rank,
            "legacy_rank": self.legacy_rank,
            "is_champion": self.is_champion,
            "is_challenger": self.is_challenger,
            "ranked": self.ranked,
            "exclusion": self.exclusion,
            "exclusion_reason": self.exclusion_reason,
            "comparability_note": self.comparability_note,
            "wape": c.wape,
            "mae": c.mae,
            "rmse": c.rmse,
            "mape": c.mape,
            "accuracy": c.accuracy,
            "smape": c.smape,
            "mase": c.mase,
            "bias": c.bias,
            "bias_abs": c.bias_abs,
            "legacy_mape": c.legacy_mape,
            "legacy_valid": c.legacy_valid,
            "validation_points": c.validation_points,
            "distinct_test_points": c.distinct_test_points,
            "origins_completed": c.origins_completed,
            "origins_total": c.origins_total,
            "failure_reason": c.failure_reason,
            "model_run_id": c.model_run_id,
        }


@dataclass
class Leaderboard:
    """The full ranking for one scope, with nothing dropped."""

    rows: list[RankedRow]
    champion_model_id: str | None
    challenger_model_id: str | None
    legacy_champion_model_id: str | None
    best_baseline_model_id: str | None
    best_baseline_wape: float | None
    beaten_by_baseline: bool
    ranked_count: int
    excluded_count: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": [row.as_dict() for row in self.rows],
            "champion_model_id": self.champion_model_id,
            "challenger_model_id": self.challenger_model_id,
            "legacy_champion_model_id": self.legacy_champion_model_id,
            "best_baseline_model_id": self.best_baseline_model_id,
            "best_baseline_wape": self.best_baseline_wape,
            "beaten_by_baseline": self.beaten_by_baseline,
            "ranked_count": self.ranked_count,
            "excluded_count": self.excluded_count,
            "notes": list(self.notes),
        }


def _effective_points(candidate: Candidate) -> int:
    """Distinct test points, falling back to validation points.

    Distinct is the honest count where two origins overlap (D-038), but a row
    written before that column existed reports only `validation_points`.
    """
    if candidate.distinct_test_points:
        return candidate.distinct_test_points
    return candidate.validation_points


def rank_candidates(
    candidates: Iterable[Candidate],
    *,
    min_validation_points: int = MIN_VALIDATION_POINTS,
    min_test_point_share: float = MIN_TEST_POINT_SHARE,
    primary_metric: str = DEFAULT_PRIMARY_METRIC,
    deployable: Callable[[Candidate], str | None] | None = None,
) -> Leaderboard:
    """Rank one scope's rows. Every input row appears in the output.

    `deployable` is an optional last gate: given a candidate, it returns the
    reason that model could not actually be fitted on this scope, or `None` if
    it could. A candidate it refuses is excluded from the ranking and the crown
    passes to the next one that can run - because a champion that cannot produce
    a forecast is not a champion, it is a blank row with a citation. The refused
    row still appears, carrying the reason, like every other exclusion here.

    It is asked last, after the cheap metric gates, so the expensive question is
    only put about rows that would otherwise have been ranked.

    Comparability is assessed **within an evaluation mode**: a `holdout_fast`
    row is measured against the best `holdout_fast` row, not against a
    `rolling_origin` one. Ranking then places all comparable rows in one order,
    because the plan being evaluated is the same six-month plan either way -
    but the mode and both point counts travel on the row so a reader can see
    the difference rather than being told it does not exist (D-037).
    """
    if primary_metric not in PRIMARY_METRIC_CHOICES:
        raise ValueError(
            f"primary_metric must be one of {list(PRIMARY_METRIC_CHOICES)}, got {primary_metric!r}"
        )
    rows = list(candidates)

    # Best observed point count per evaluation mode, computed over completed
    # rows with a usable primary metric - a failed row's zero must not lower
    # the bar the others are held to.
    best_by_mode: dict[str | None, int] = {}
    for candidate in rows:
        if candidate.status != _RANKABLE_STATUS or candidate.primary(primary_metric) is None:
            continue
        mode = candidate.evaluation_mode
        best_by_mode[mode] = max(best_by_mode.get(mode, 0), _effective_points(candidate))

    ranked: list[Candidate] = []
    verdicts: dict[str, tuple[str | None, str | None, str | None]] = {}

    for candidate in rows:
        note: str | None = None
        mode_best = best_by_mode.get(candidate.evaluation_mode, 0)
        if mode_best:
            note = (
                f"{_effective_points(candidate)} of {mode_best} distinct test "
                f"points available in mode {candidate.evaluation_mode!r}"
            )

        if candidate.is_baseline:
            verdicts[candidate.model_id] = (
                Ineligibility.IS_BASELINE.value,
                INELIGIBILITY_REASONS[Ineligibility.IS_BASELINE],
                note,
            )
            continue
        if candidate.status != _RANKABLE_STATUS:
            verdicts[candidate.model_id] = (
                Ineligibility.NOT_COMPLETED.value,
                INELIGIBILITY_REASONS[Ineligibility.NOT_COMPLETED],
                note,
            )
            continue
        if candidate.primary(primary_metric) is None:
            verdicts[candidate.model_id] = (
                Ineligibility.NO_PRIMARY_METRIC.value,
                INELIGIBILITY_REASONS[Ineligibility.NO_PRIMARY_METRIC],
                note,
            )
            continue
        if _effective_points(candidate) < min_validation_points:
            verdicts[candidate.model_id] = (
                Ineligibility.TOO_FEW_VALIDATION_POINTS.value,
                INELIGIBILITY_REASONS[Ineligibility.TOO_FEW_VALIDATION_POINTS],
                note,
            )
            continue
        if mode_best and _effective_points(candidate) < mode_best * min_test_point_share:
            verdicts[candidate.model_id] = (
                Ineligibility.INCOMPARABLE_TEST_WINDOW.value,
                INELIGIBILITY_REASONS[Ineligibility.INCOMPARABLE_TEST_WINDOW],
                note,
            )
            continue
        if deployable is not None:
            refusal = deployable(candidate)
            if refusal is not None:
                verdicts[candidate.model_id] = (
                    Ineligibility.NOT_DEPLOYABLE.value,
                    # The adapter's own words, not a paraphrase: the reader
                    # needs the requirement that was missed, not the category.
                    refusal,
                    note,
                )
                continue
        verdicts[candidate.model_id] = (None, None, note)
        ranked.append(candidate)

    # Primary metric, then absolute bias, then MAE, then a deterministic
    # model-id tie-break. Bias is the second key precisely because the primary
    # metric is one-sided: between two models the metric cannot separate, the
    # less biased one wins.
    ranked.sort(
        key=lambda c: (
            _inf_if_none(c.primary(primary_metric)),
            c.sort_bias_abs(),
            _inf_if_none(c.mae),
            c.model_id,
        )
    )
    rank_by_model = {c.model_id: index + 1 for index, c in enumerate(ranked)}

    # The legacy ranking is computed over the same rows but by its own rule,
    # and only over rows the references would have considered valid.
    legacy_pool = [
        c
        for c in rows
        if not c.is_baseline
        and c.status == _RANKABLE_STATUS
        and c.legacy_valid
        and c.legacy_mape is not None
    ]
    legacy_pool.sort(key=lambda c: (c.legacy_mape, c.model_id))
    legacy_rank_by_model = {c.model_id: i + 1 for i, c in enumerate(legacy_pool)}

    champion = ranked[0].model_id if ranked else None
    challenger = ranked[1].model_id if len(ranked) > 1 else None
    legacy_champion = legacy_pool[0].model_id if legacy_pool else None

    # A baseline is compared on the same metric the champion was chosen by,
    # or the comparison would be between two different measurements.
    baselines = [
        c
        for c in rows
        if c.is_baseline
        and c.status == _RANKABLE_STATUS
        and c.primary(primary_metric) is not None
    ]
    baselines.sort(key=lambda c: (_inf_if_none(c.primary(primary_metric)), c.model_id))
    best_baseline = baselines[0] if baselines else None

    beaten = bool(
        best_baseline
        and ranked
        and best_baseline.primary(primary_metric) is not None
        and ranked[0].primary(primary_metric) is not None
        and best_baseline.primary(primary_metric) < ranked[0].primary(primary_metric)
    )

    notes: list[str] = []
    if beaten and best_baseline is not None and ranked:
        notes.append(
            f"The best non-registry baseline ({best_baseline.model_id}, "
            f"{primary_metric.upper()} "
            f"{best_baseline.primary(primary_metric):.4f}) beats the champion "
            f"({ranked[0].model_id}, {primary_metric.upper()} "
            f"{ranked[0].primary(primary_metric):.4f}). The champion "
            "is still the best of the 13 registered models; it is not the best "
            "available forecast for this scope."
        )
    if not ranked:
        notes.append(
            "No registered model produced a rankable metric in this scope. "
            "Every row is shown with its status and reason; none was "
            "substituted or hidden."
        )
    modes = {
        c.evaluation_mode
        for c in ranked
        if c.evaluation_mode is not None
    }
    if len(modes) > 1:
        notes.append(
            "This ranking mixes evaluation modes "
            f"({', '.join(sorted(modes))}). Point counts differ by mode "
            "(docs/DECISIONS.md D-037) and are shown on every row."
        )

    out_rows = [
        RankedRow(
            candidate=candidate,
            rank=rank_by_model.get(candidate.model_id),
            legacy_rank=legacy_rank_by_model.get(candidate.model_id),
            is_champion=candidate.model_id == champion and not candidate.is_baseline,
            is_challenger=candidate.model_id == challenger,
            ranked=candidate.model_id in rank_by_model,
            exclusion=verdicts[candidate.model_id][0],
            exclusion_reason=verdicts[candidate.model_id][1],
            comparability_note=verdicts[candidate.model_id][2],
        )
        for candidate in rows
    ]
    # Ranked rows first in rank order, then everything else in a stable,
    # readable order. Nothing is dropped by the sort.
    out_rows.sort(
        key=lambda row: (
            0 if row.rank is not None else (1 if not row.candidate.is_baseline else 2),
            row.rank if row.rank is not None else 0,
            row.candidate.model_id,
        )
    )

    return Leaderboard(
        rows=out_rows,
        champion_model_id=champion,
        challenger_model_id=challenger,
        legacy_champion_model_id=legacy_champion,
        best_baseline_model_id=best_baseline.model_id if best_baseline else None,
        best_baseline_wape=best_baseline.wape if best_baseline else None,
        beaten_by_baseline=beaten,
        ranked_count=len(ranked),
        excluded_count=len(rows) - len(ranked),
        notes=notes,
    )


def _inf_if_none(value: float | None) -> float:
    return float("inf") if value is None else value


def compare_to_baseline(
    champion_wape: float | None, baseline_wape: float | None
) -> dict[str, Any]:
    """The skill score, stated in both directions.

    Returned as a dict rather than a bare number so the sign convention cannot
    be misread: `improvement_pct` is positive when the champion is better.
    """
    if champion_wape is None or baseline_wape is None or baseline_wape == 0:
        return {
            "improvement_pct": None,
            "champion_better": None,
            "reason": (
                "Undefined: one of the two WAPE values is missing, or the "
                "baseline's is zero."
            ),
        }
    improvement = (baseline_wape - champion_wape) / baseline_wape * 100.0
    return {
        "improvement_pct": improvement,
        "champion_better": improvement > 0,
        "reason": None,
    }


def group_candidates(
    rows: Sequence[dict[str, Any]], *, key: str
) -> dict[Any, list[dict[str, Any]]]:
    """Split rows by a grouping column, preserving order within each group."""
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get(key), []).append(row)
    return grouped
