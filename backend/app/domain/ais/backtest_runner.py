"""AIS wiring for the generic backtester.

`app/ml/evaluation/` knows nothing about AIS columns. This module is where the
panel's schema meets it: it resolves origins from the panel's own period range,
attaches the calendar exogenous set, classifies the series' demand segment, and
hands the generic backtester column names.

Two AIS-specific facts are attached to every report because they change how the
numbers should be read, and neither is visible from the metrics alone:

**The mandated primary origin trains mostly on the sales proxy and validates
entirely on ordered demand.** Measured on the panel: 59.66% of the primary
origin's training rows are `sales_proxy`, while 100% of its validation rows are
`order`. That is not leakage - the proxy is genuinely all that exists before
2025-04 - but it means the primary origin measures cross-signal
generalisation, not same-signal accuracy. `target_source_mix` reports it per
window so the caveat travels with the result (`docs/DECISIONS.md` D-040).

**Some validation actuals are censored.** An order line despatched short leaves
the ordered quantity as a lower bound. Those points are scored rather than
dropped - excluding them would bias the metric toward easy months - but they
are counted, so a window that is largely censored can be read with that in
mind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pandas as pd

from app.domain.ais.exog_features import prepare_local_series_frame
from app.ml.adapters.base import ModelContext
from app.ml.evaluation.backtest import (
    EvaluationBudget,
    ModelEvaluation,
    backtest_all_models,
    backtest_baselines,
)
from app.ml.evaluation.folds import Origin, aggregate_test_points, build_origins
from app.ml.evaluation.quantiles import ResidualStore
from app.ml.evaluation.segmentation import DemandSegment, profile_series
from app.ml.features.panel import month_index

#: The panel's own column names. The only place they appear in the evaluation
#: path, per the boundary rule in CLAUDE.md.
SERIES_COL = "series_id"
PERIOD_COL = "period_index"
TARGET_COL = "target"
CENSORED_COL = "is_censored"
TARGET_SOURCE_COL = "target_source"


@dataclass
class SeriesBacktestReport:
    """One series' full backtest: the 13, the baselines, and the caveats."""

    series_id: str
    segment: str
    observed_months: int
    adi: float | None
    cv_squared: float | None
    origins: list[dict[str, Any]] = field(default_factory=list)
    total_test_periods: int = 0
    distinct_test_periods: int = 0
    models: dict[str, ModelEvaluation] = field(default_factory=dict)
    baselines: dict[str, ModelEvaluation] = field(default_factory=dict)
    target_source_mix: dict[str, dict[str, int]] = field(default_factory=dict)
    censored_counts: dict[str, int] = field(default_factory=dict)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for evaluation in self.models.values():
            counts[evaluation.status.value] = counts.get(evaluation.status.value, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "segment": self.segment,
            "observed_months": self.observed_months,
            "adi": self.adi,
            "cv_squared": self.cv_squared,
            "origins": list(self.origins),
            "total_test_periods": self.total_test_periods,
            "distinct_test_periods": self.distinct_test_periods,
            "status_counts": self.status_counts(),
            "models": {key: value.as_dict() for key, value in self.models.items()},
            "baselines": {key: value.as_dict() for key, value in self.baselines.items()},
            "target_source_mix": self.target_source_mix,
            "censored_counts": self.censored_counts,
        }


def resolve_origins(
    panel: pd.DataFrame,
    *,
    period_col: str = PERIOD_COL,
    max_origins: int = 2,
) -> list[Origin]:
    """Origins from the panel's own period range.

    Derived from the data rather than hardcoded, so a re-ingested panel with a
    different range produces the origins that range can support instead of
    silently producing none.
    """
    if panel.empty:
        return []
    return build_origins(
        int(panel[period_col].min()),
        int(panel[period_col].max()),
        max_origins=max_origins,
    )


def backtest_one_series(
    panel: pd.DataFrame,
    series_id: str,
    *,
    origins: Sequence[Origin] | None = None,
    model_ids: Iterable[str] | None = None,
    profile: str = "reference",
    residual_store: ResidualStore | None = None,
    budget: EvaluationBudget | None = None,
    include_baselines: bool = True,
    allow_actuals_in_recursion: bool = False,
) -> SeriesBacktestReport:
    """Backtest all 13 models plus the baselines on one series.

    `panel` may be the whole panel or a single series' slice; the series is
    selected here either way, and sorted by period, because several adapters
    assume chronological order and a shuffled frame would produce a plausible
    and wrong answer rather than an error.
    """
    series = panel[panel[SERIES_COL] == series_id].sort_values(PERIOD_COL)
    if series.empty:
        raise KeyError(f"{series_id!r} is not in this panel")

    resolved_origins = list(
        origins if origins is not None else resolve_origins(panel)
    )
    prepared, exog_columns = prepare_local_series_frame(series, period_col=PERIOD_COL)
    sparsity = profile_series(series[TARGET_COL])

    total, distinct = aggregate_test_points(resolved_origins)
    report = SeriesBacktestReport(
        series_id=series_id,
        segment=sparsity.segment.value,
        observed_months=sparsity.observed_months,
        adi=sparsity.adi,
        cv_squared=sparsity.cv_squared,
        origins=[origin.as_dict() for origin in resolved_origins],
        total_test_periods=total,
        distinct_test_periods=distinct,
        target_source_mix=_target_source_mix(series, resolved_origins),
        censored_counts=_censored_counts(series, resolved_origins),
    )

    context = ModelContext(
        exog_columns=exog_columns,
        min_history_profile=profile,
        allow_actuals_in_recursion=allow_actuals_in_recursion,
    )
    report.models = backtest_all_models(
        prepared,
        resolved_origins,
        model_ids=model_ids,
        period_col=PERIOD_COL,
        target_col=TARGET_COL,
        censored_col=CENSORED_COL,
        base_context=context,
        exog_columns=exog_columns,
        segment=sparsity.segment.value,
        residual_store=residual_store,
        budget=budget,
    )
    if include_baselines:
        report.baselines = backtest_baselines(
            prepared,
            resolved_origins,
            period_col=PERIOD_COL,
            target_col=TARGET_COL,
            profile=profile,
        )
    return report


def _window_slices(
    series: pd.DataFrame, origins: Sequence[Origin]
) -> dict[str, pd.DataFrame]:
    """Named train/validation slices, one pair per origin."""
    slices: dict[str, pd.DataFrame] = {}
    for origin in origins:
        slices[f"{origin.name}_train"] = series[
            series[PERIOD_COL] <= origin.train_end_index
        ]
        slices[f"{origin.name}_validation"] = series[
            (series[PERIOD_COL] >= origin.validation_start_index)
            & (series[PERIOD_COL] <= origin.validation_end_index)
        ]
    return slices


def _target_source_mix(
    series: pd.DataFrame, origins: Sequence[Origin]
) -> dict[str, dict[str, int]]:
    """`order` vs `sales_proxy` row counts per origin window.

    Reported because the primary origin trains largely on the proxy and
    validates entirely on ordered demand. Calling those two signals equivalent
    is forbidden, so the composition is stated rather than assumed.
    """
    if TARGET_SOURCE_COL not in series.columns:
        return {}
    return {
        name: {
            str(key): int(value)
            for key, value in frame[TARGET_SOURCE_COL].value_counts(dropna=False).items()
        }
        for name, frame in _window_slices(series, origins).items()
    }


def _censored_counts(series: pd.DataFrame, origins: Sequence[Origin]) -> dict[str, int]:
    """Censored rows per origin window - actuals that are lower bounds."""
    if CENSORED_COL not in series.columns:
        return {}
    return {
        name: int(frame[CENSORED_COL].fillna(False).astype(bool).sum())
        for name, frame in _window_slices(series, origins).items()
    }


def panel_target_source_mix(
    panel: pd.DataFrame, origins: Sequence[Origin]
) -> dict[str, dict[str, Any]]:
    """The same composition across the **whole panel**, for the run report.

    A per-series mix answers "how should I read this row"; this answers "how
    should I read this leaderboard", which is the question a reviewer of the
    run actually has.
    """
    if TARGET_SOURCE_COL not in panel.columns:
        return {}
    summary: dict[str, dict[str, Any]] = {}
    for origin in origins:
        for label, frame in (
            ("train", panel[panel[PERIOD_COL] <= origin.train_end_index]),
            (
                "validation",
                panel[
                    (panel[PERIOD_COL] >= origin.validation_start_index)
                    & (panel[PERIOD_COL] <= origin.validation_end_index)
                ],
            ),
        ):
            counts = frame[TARGET_SOURCE_COL].value_counts(dropna=False)
            rows = int(counts.sum())
            summary[f"{origin.name}_{label}"] = {
                "rows": rows,
                "counts": {str(k): int(v) for k, v in counts.items()},
                "shares": {
                    str(k): round(int(v) / rows * 100, 2) for k, v in counts.items()
                }
                if rows
                else {},
                "censored_rows": int(
                    frame[CENSORED_COL].fillna(False).astype(bool).sum()
                )
                if CENSORED_COL in frame.columns
                else None,
            }
    return summary


def segment_of(series_target: Iterable[Any]) -> DemandSegment:
    """The demand segment for a target series. Thin, but named at the boundary
    so callers do not import the classifier directly and drift from it."""
    return profile_series(list(series_target)).segment


def period_index_of(period: str) -> int:
    """`YYYY-MM` to the panel's absolute month counter."""
    return month_index(period)
