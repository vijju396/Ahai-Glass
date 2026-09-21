"""Can a model actually run on a scope's whole history?

A backtest fits on a training window that stops short of the fold it is scored
against. A live forecast fits on everything. Those are not the same data, and a
model can be eligible on the first and refuse the second. VAR is the clear
case: it needs several inputs that all move, and a column that varied over the
eighteen months of fold 1 can be flat across all twenty-eight.

Until this module existed, that gap was only discovered at forecast time.
`BENGALURU|FG.MYS.BCK.G00300A000` crowned `var_exog` on a 25.5% WAPE, the refit
refused, and the row came back with a stated reason and no number. Honest, but a
plant with nothing to produce against for that SKU - while three other models
had ranked below it and could have run.

Two things live here, and they exist as one module because they must not drift
apart: the construction of the frame and context a scope is fitted with, and the
eligibility question asked about them. Champion selection asks the question
before awarding the crown; the forecast run builds the same frame to fit on. If
the two ever built a different context, the check would be answering about data
that is not the data.

Nothing here fits a model. `validate_eligibility` inspects the frame and
returns, so the cost is one adapter construction per candidate per scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import pandas as pd

from app.domain.ais.backtest_runner import PERIOD_COL, TARGET_COL
from app.domain.ais.exog_features import prepare_local_series_frame
from app.domain.ais.scope_builder import AGGREGATE_VAR_PAIR_COLUMN
from app.ml.adapters.base import ModelContext
from app.ml.evaluation.seasonality import resolve_seasonal_period
from app.ml.registry.model_registry import MODEL_REGISTRY

#: The paired column VAR reads at series level. An aggregate scope pairs against
#: its active-cell count instead, which is what `scope_builder` records.
SERIES_VAR_PAIR_COLUMN = "despatched_qty"


@dataclass(frozen=True)
class ScopeFit:
    """Everything needed to fit one scope, and the reasoning behind it."""

    frame: pd.DataFrame
    context: ModelContext
    exog_columns: tuple[str, ...]
    seasonal: Any

    @property
    def history_months(self) -> int:
        return int(len(self.frame))


def prepare_scope_fit(
    scope_frame: pd.DataFrame,
    *,
    scope_level: str,
    horizons: Sequence[int],
    config: dict[str, Any],
) -> ScopeFit:
    """The frame and context a scope's champion will be refitted on.

    The single definition of it. `forecast_service` fits on exactly this, and
    `champion_service` asks its eligibility question about exactly this.
    """
    frame, exog_columns = prepare_local_series_frame(scope_frame, period_col=PERIOD_COL)
    frame = frame.sort_values(PERIOD_COL).reset_index(drop=True)
    seasonal = resolve_seasonal_period(
        frame[TARGET_COL], profile=str(config["min_history_profile"])
    )
    context = ModelContext(
        seasonal_period=seasonal.period,
        exog_columns=exog_columns,
        horizons=tuple(int(h) for h in horizons),
        random_seed=int(config["random_seed"]),
        min_history_profile=str(config["min_history_profile"]),
        xgboost_training_profile=str(config["xgboost_training_profile"]),
        var_pair_column=(
            SERIES_VAR_PAIR_COLUMN
            if scope_level == "series"
            else AGGREGATE_VAR_PAIR_COLUMN
        ),
    )
    return ScopeFit(
        frame=frame,
        context=context,
        exog_columns=tuple(exog_columns),
        seasonal=seasonal,
    )


def refusal_reason(model_id: str, fit: ScopeFit) -> str | None:
    """Why this model cannot be fitted on this history, or `None` if it can.

    The adapter's own `validate_eligibility` answers it - the same call the
    refit makes - rather than a second opinion written here that could disagree
    with the one that matters.
    """
    factory = MODEL_REGISTRY.get(model_id)
    if factory is None:
        return f"{model_id!r} is not in the model registry."
    verdict = factory(fit.context).validate_eligibility(fit.frame, fit.context)
    if verdict.eligible:
        return None
    return verdict.reason or "The model reported itself ineligible without a reason."


def refusals(model_ids: Iterable[str], fit: ScopeFit) -> dict[str, str]:
    """Only the models that cannot run, mapped to why."""
    found: dict[str, str] = {}
    for model_id in model_ids:
        reason = refusal_reason(model_id, fit)
        if reason is not None:
            found[model_id] = reason
    return found
