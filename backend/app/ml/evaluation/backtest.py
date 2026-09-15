"""Rolling-origin backtesting for one series.

This module is the only place that decides what a model's evaluation *status*
is, so the vocabulary in `docs/STATUS.md` and `CLAUDE.md` has exactly one
implementation:

| Status | Meaning here |
|---|---|
| `COMPLETED` | fitted, predicted, metrics computed |
| `INELIGIBLE` | a *validated* data requirement was unmet; the requirement and its remediation are attached |
| `FAILED` | the fit or the prediction raised; the exception is attached |
| `TIMED_OUT` | the fit exceeded its per-model budget (see the caveat on `EvaluationBudget`) |
| `NOT_EVALUATED_BUDGET` | the run budget was exhausted before this model was reached |

**Every model that was asked for comes back**, whatever happened to it. A model
never disappears, and a model that did not produce a forecast is never given a
zero one - its metrics are `None` and its status says why.

**One model's failure never stops another.** Each model is evaluated inside its
own `try`, exactly as both references do (Meriton `training_service.py:441-451`,
Sodexo `engine.py:106-123`).

The module holds no dataset-specific column name; the caller passes the column
names and the prepared frame. AIS's wiring lives in
`app/domain/ais/backtest_runner.py`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

from app.ml.adapters.base import (
    Eligibility,
    ForecastModelAdapter,
    ModelContext,
)
from app.ml.evaluation.baselines import forecast_all_baselines
from app.ml.evaluation.folds import Origin, fast_holdout_origin
from app.ml.evaluation.metrics import MetricSet, evaluate, reference_metrics
from app.ml.evaluation.quantiles import ResidualStore
from app.ml.evaluation.seasonality import resolve_seasonal_period
from app.ml.features.panel import index_to_period, month_index
from app.schemas.common import EvaluationMode, ModelRunStatus

AdapterFactory = Callable[[ModelContext], ForecastModelAdapter]

#: How far above the training window's largest value a forecast may go before
#: it is treated as divergent rather than merely aggressive.
#:
#: Both reference projects fit SARIMAX with `enforce_stationarity=False` and
#: `enforce_invertibility=False` (docs/MODEL_INVENTORY.md SS2), which AIS
#: preserves for parity. On AIS's short intermittent monthly series that
#: setting sometimes yields AR roots outside the unit circle and a forecast
#: that grows geometrically: measured on the real panel, `sarimax` on
#: `JALANDHAR|FG.M11.FDR.G00320A000` returned 3.67e11 units against actuals of
#: 0-10, and a single such series moved the pooled pinball loss by seven orders
#: of magnitude.
#:
#: The fitter is left exactly as the references have it. The guard sits at the
#: evaluation boundary instead: a divergent forecast is reported `FAILED` with
#: its measured magnitude, so it neither wins nor silently poisons a pooled
#: metric (docs/DECISIONS.md D-041). The factor is deliberately loose - 100x
#: the largest month ever observed is far beyond any real demand swing, so this
#: catches divergence and not ambition.
FORECAST_MAGNITUDE_FACTOR = 100.0

#: Absolute ceiling for a training window whose values are all zero, where a
#: relative bound would reject every non-zero forecast.
FORECAST_MAGNITUDE_FLOOR = 1_000.0


def forecast_magnitude_bound(training_values: Sequence[Any]) -> float:
    """The largest magnitude a forecast may take for this training window."""
    numeric = pd.to_numeric(pd.Series(list(training_values)), errors="coerce").dropna()
    observed_max = float(numeric.abs().max()) if len(numeric) else 0.0
    return max(observed_max * FORECAST_MAGNITUDE_FACTOR, FORECAST_MAGNITUDE_FLOOR)


@dataclass
class EvaluationBudget:
    """A wall-clock budget for one backtest run.

    **What this does and does not do.** It refuses to *start* a model once the
    run budget is spent (`NOT_EVALUATED_BUDGET`) and it marks a fit that
    overran its per-model allowance `TIMED_OUT`, discarding that fit's metrics
    so an overrunning model cannot win. It does **not** interrupt a fit that is
    already running: statsmodels, pmdarima, XGBoost and TensorFlow spend their
    time inside C extensions where a Python-level timer cannot pre-empt them.
    Real pre-emption needs a subprocess per fit, which belongs with the job
    runner in Phase 7 - the budget is honest about being a post-hoc verdict
    plus an admission gate until then (`docs/DECISIONS.md` D-039).
    """

    total_seconds: float | None = None
    per_model_seconds: float | None = None
    _started: float = field(default_factory=time.perf_counter)

    def reset(self) -> None:
        self._started = time.perf_counter()

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self._started

    def exhausted(self) -> bool:
        return self.total_seconds is not None and self.elapsed_seconds >= self.total_seconds

    def overran(self, duration_seconds: float) -> bool:
        return (
            self.per_model_seconds is not None
            and duration_seconds > self.per_model_seconds
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "per_model_seconds": self.per_model_seconds,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass
class OriginResult:
    """What happened to one model at one origin."""

    origin_name: str
    fold_index: int
    train_end_period: str
    train_rows: int
    status: ModelRunStatus
    seasonal_period: int | None = None
    metrics: MetricSet | None = None
    legacy_metrics: dict[str, float | None] = field(default_factory=dict)
    periods: list[str] = field(default_factory=list)
    horizons: list[int] = field(default_factory=list)
    actuals: list[float] = field(default_factory=list)
    predictions: list[float] = field(default_factory=list)
    eligibility: Eligibility | None = None
    failure_reason: str | None = None
    fit_seconds: float | None = None
    predict_seconds: float | None = None
    negative_predictions: int = 0
    max_abs_prediction: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "origin_name": self.origin_name,
            "fold_index": self.fold_index,
            "train_end_period": self.train_end_period,
            "train_rows": self.train_rows,
            "status": self.status.value,
            "seasonal_period": self.seasonal_period,
            "metrics": None if self.metrics is None else self.metrics.as_dict(),
            "legacy_metrics": dict(self.legacy_metrics),
            "periods": list(self.periods),
            "horizons": list(self.horizons),
            # Actuals and predictions are persisted, not just summarised into
            # metrics. Phase 8's diagnostics owe an actual-versus-predicted
            # chart, a residual chart and horizon-level performance, and none of
            # the three can be reconstructed from a WAPE. Six values per origin
            # per model is a cost worth paying for evidence that can be checked.
            "actuals": [float(value) for value in self.actuals],
            "predictions": [float(value) for value in self.predictions],
            "eligibility": None if self.eligibility is None else self.eligibility.as_dict(),
            "failure_reason": self.failure_reason,
            "fit_seconds": self.fit_seconds,
            "predict_seconds": self.predict_seconds,
            "negative_predictions": self.negative_predictions,
            "max_abs_prediction": self.max_abs_prediction,
        }


@dataclass
class ModelEvaluation:
    """One model's whole backtest across every origin it was evaluated on."""

    model_id: str
    display_name: str
    status: ModelRunStatus
    evaluation_mode: EvaluationMode
    origins: list[OriginResult] = field(default_factory=list)
    pooled: MetricSet | None = None
    pooled_legacy: dict[str, float | None] = field(default_factory=dict)
    distinct_test_points: int = 0
    total_test_points: int = 0
    duplicate_test_points: int = 0
    reason: str | None = None

    @property
    def completed_origins(self) -> list[OriginResult]:
        return [o for o in self.origins if o.status is ModelRunStatus.COMPLETED]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "evaluation_mode": self.evaluation_mode.value,
            "origins": [o.as_dict() for o in self.origins],
            "pooled": None if self.pooled is None else self.pooled.as_dict(),
            "pooled_legacy": dict(self.pooled_legacy),
            "distinct_test_points": self.distinct_test_points,
            "total_test_points": self.total_test_points,
            "duplicate_test_points": self.duplicate_test_points,
            "reason": self.reason,
        }


def backtest_model(
    frame: pd.DataFrame,
    adapter_factory: AdapterFactory,
    origins: Sequence[Origin],
    *,
    period_col: str = "period_index",
    target_col: str = "target",
    censored_col: str | None = None,
    base_context: ModelContext | None = None,
    exog_columns: Sequence[str] = (),
    segment: str = "unknown",
    residual_store: ResidualStore | None = None,
    budget: EvaluationBudget | None = None,
    uses_fast_holdout: bool | None = None,
) -> ModelEvaluation:
    """Backtest one model on one series across `origins`.

    A fresh adapter is built per origin, so nothing - fitted state, resolved
    hyperparameters, a scaler - can survive from one fold into the next. The
    seasonal period is likewise resolved **from that origin's training window
    only**; resolving it once on the full series would let the last six months
    influence a fold that is supposed not to have seen them.
    """
    context_template = base_context or ModelContext()
    probe = adapter_factory(context_template)
    fast_holdout = probe.uses_fast_holdout if uses_fast_holdout is None else uses_fast_holdout

    if fast_holdout:
        chosen = fast_holdout_origin(origins)
        selected: list[Origin] = [chosen] if chosen else []
        mode = EvaluationMode.HOLDOUT_FAST
    else:
        selected = list(origins)
        mode = (
            EvaluationMode.ROLLING_ORIGIN
            if len(selected) > 1
            else EvaluationMode.HOLDOUT_FALLBACK
        )

    evaluation = ModelEvaluation(
        model_id=probe.model_id,
        display_name=probe.display_name,
        status=ModelRunStatus.NOT_EVALUATED_BUDGET,
        evaluation_mode=mode,
    )

    if not selected:
        evaluation.status = ModelRunStatus.NOT_EVALUATED_BUDGET
        evaluation.reason = (
            "the panel supports no origin with enough training history for an "
            "honest fold, so this model was not evaluated rather than being "
            "evaluated on an invented one"
        )
        return evaluation

    for origin in selected:
        evaluation.origins.append(
            _run_one_origin(
                frame=frame,
                adapter_factory=adapter_factory,
                origin=origin,
                period_col=period_col,
                target_col=target_col,
                censored_col=censored_col,
                context_template=context_template,
                exog_columns=exog_columns,
                segment=segment,
                residual_store=residual_store,
                budget=budget,
            )
        )

    _finalise(evaluation, frame, period_col=period_col, target_col=target_col)
    return evaluation


def _run_one_origin(
    *,
    frame: pd.DataFrame,
    adapter_factory: AdapterFactory,
    origin: Origin,
    period_col: str,
    target_col: str,
    censored_col: str | None,
    context_template: ModelContext,
    exog_columns: Sequence[str],
    segment: str,
    residual_store: ResidualStore | None,
    budget: EvaluationBudget | None,
) -> OriginResult:
    train = frame[frame[period_col] <= origin.train_end_index].sort_values(period_col)
    validation = frame[
        (frame[period_col] >= origin.validation_start_index)
        & (frame[period_col] <= origin.validation_end_index)
    ].sort_values(period_col)

    result = OriginResult(
        origin_name=origin.name,
        fold_index=origin.fold_index,
        train_end_period=origin.train_end_period,
        train_rows=len(train),
        status=ModelRunStatus.INELIGIBLE,
    )

    if validation.empty:
        result.status = ModelRunStatus.INELIGIBLE
        result.eligibility = Eligibility(
            eligible=False,
            reason="this series has no observation inside the validation window",
            remediation=(
                "nothing to remediate - the series simply does not extend into "
                f"{origin.validation_periods[0]}..{origin.validation_periods[-1]}"
            ),
        )
        return result

    if budget is not None and budget.exhausted():
        result.status = ModelRunStatus.NOT_EVALUATED_BUDGET
        result.failure_reason = (
            f"the run budget of {budget.total_seconds}s was already spent when this "
            "origin was reached"
        )
        return result

    # Resolved from the training window only. See the docstring.
    resolution = resolve_seasonal_period(
        train[target_col], profile=context_template.min_history_profile
    )
    context = ModelContext(
        seasonal_period=resolution.period,
        exog_columns=tuple(exog_columns),
        horizons=context_template.horizons,
        random_seed=context_template.random_seed,
        min_history_profile=context_template.min_history_profile,
        xgboost_training_profile=context_template.xgboost_training_profile,
        timeout_seconds=context_template.timeout_seconds,
        var_pair_column=context_template.var_pair_column,
        allow_actuals_in_recursion=context_template.allow_actuals_in_recursion,
    )
    result.seasonal_period = resolution.period

    adapter = adapter_factory(context)
    eligibility = adapter.validate_eligibility(train, context)
    result.eligibility = eligibility
    if not eligibility.eligible:
        result.status = ModelRunStatus.INELIGIBLE
        return result

    started = time.perf_counter()
    try:
        adapter.fit(train, context)
        result.fit_seconds = time.perf_counter() - started
        predict_started = time.perf_counter()
        predictions = adapter.predict(validation, context)
        result.predict_seconds = time.perf_counter() - predict_started
    except Exception as exc:  # noqa: BLE001 - isolation is the point
        result.status = ModelRunStatus.FAILED
        result.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
        result.fit_seconds = result.fit_seconds or (time.perf_counter() - started)
        return result

    if budget is not None and budget.overran(result.fit_seconds or 0.0):
        result.status = ModelRunStatus.TIMED_OUT
        result.failure_reason = (
            f"the fit took {result.fit_seconds:.1f}s against a per-model budget of "
            f"{budget.per_model_seconds}s, so its metrics are discarded rather than "
            "compared against models that stayed inside the budget"
        )
        return result

    # Divergence guard. See FORECAST_MAGNITUDE_FACTOR: the fit is the
    # reference's, the refusal to score a runaway forecast is ours.
    finite = pd.to_numeric(predictions, errors="coerce").dropna()
    result.max_abs_prediction = float(finite.abs().max()) if len(finite) else None
    result.negative_predictions = int((finite < 0).sum())
    bound = forecast_magnitude_bound(train[target_col])
    if result.max_abs_prediction is not None and result.max_abs_prediction > bound:
        result.status = ModelRunStatus.FAILED
        result.failure_reason = (
            f"forecast diverged: largest magnitude {result.max_abs_prediction:.3g} "
            f"exceeds {FORECAST_MAGNITUDE_FACTOR:g}x the largest observed training "
            f"value (bound {bound:.3g}). The fit is kept as the reference "
            "projects configure it; the forecast is not scored, because a "
            "divergent series would dominate every pooled metric it entered."
        )
        return result

    actuals = pd.to_numeric(validation[target_col], errors="coerce")
    censored = (
        validation[censored_col]
        if censored_col is not None and censored_col in validation.columns
        else None
    )

    result.periods = [index_to_period(int(p)) for p in validation[period_col].tolist()]
    result.horizons = [
        origin.horizon_of(int(p)) or 0 for p in validation[period_col].tolist()
    ]
    result.actuals = actuals.tolist()
    result.predictions = predictions.tolist()
    result.metrics = evaluate(
        result.actuals,
        result.predictions,
        insample_actuals=train[target_col].tolist(),
        seasonal_period=resolution.period,
        censored=None if censored is None else censored.tolist(),
    )
    result.legacy_metrics = reference_metrics(result.actuals, result.predictions)
    result.status = ModelRunStatus.COMPLETED

    if residual_store is not None:
        for horizon, actual, prediction in zip(
            result.horizons, result.actuals, result.predictions
        ):
            residual_store.add(
                adapter.model_id, int(horizon), segment, [actual], [prediction]
            )

    return result


def _finalise(
    evaluation: ModelEvaluation,
    frame: pd.DataFrame,
    *,
    period_col: str,
    target_col: str,
) -> None:
    """Pool across origins over **distinct** test points, and set the status.

    Averaging per-origin metrics would double-weight any month two origins both
    validate on - the mandated pair overlaps on two of six (`folds.py`). So the
    pooled metric is computed from the underlying pairs de-duplicated by
    period, keeping the prediction from the origin with the **most training
    history**, which is the one a deployment would actually have used.
    """
    completed = evaluation.completed_origins
    if not completed:
        first = evaluation.origins[0]
        evaluation.status = first.status
        evaluation.reason = first.failure_reason or (
            first.eligibility.reason if first.eligibility else None
        )
        return

    by_period: dict[str, tuple[int, float, float]] = {}
    total = 0
    for origin_result in completed:
        rank = origin_result.fold_index
        for period, actual, prediction in zip(
            origin_result.periods, origin_result.actuals, origin_result.predictions
        ):
            total += 1
            existing = by_period.get(period)
            if existing is None or rank >= existing[0]:
                by_period[period] = (rank, actual, prediction)

    ordered = [by_period[key] for key in sorted(by_period)]
    actuals = [row[1] for row in ordered]
    predictions = [row[2] for row in ordered]

    latest = max(completed, key=lambda o: o.fold_index)
    insample = frame[frame[period_col] <= month_index(latest.train_end_period)]

    evaluation.total_test_points = total
    evaluation.distinct_test_points = len(ordered)
    evaluation.duplicate_test_points = total - len(ordered)
    evaluation.pooled = evaluate(
        actuals,
        predictions,
        insample_actuals=insample[target_col].tolist(),
        seasonal_period=latest.seasonal_period,
    )
    evaluation.pooled_legacy = reference_metrics(actuals, predictions)
    evaluation.status = ModelRunStatus.COMPLETED

    not_completed = [o for o in evaluation.origins if o.status is not ModelRunStatus.COMPLETED]
    if not_completed:
        evaluation.reason = (
            f"{len(completed)} of {len(evaluation.origins)} origins completed; "
            + ", ".join(f"{o.origin_name}: {o.status.value}" for o in not_completed)
        )


def backtest_baselines(
    frame: pd.DataFrame,
    origins: Sequence[Origin],
    *,
    period_col: str = "period_index",
    target_col: str = "target",
    profile: str = "reference",
) -> dict[str, ModelEvaluation]:
    """The four non-registry baselines, evaluated on the same origins.

    Reported next to the leaderboard, never on it. `ModelEvaluation` is reused
    for the shape only; a baseline can never be champion, which
    `canonical_models.assert_canonical_registry()` enforces by keeping the id
    sets disjoint.
    """
    results: dict[str, ModelEvaluation] = {}
    for origin in origins:
        train = frame[frame[period_col] <= origin.train_end_index].sort_values(period_col)
        validation = frame[
            (frame[period_col] >= origin.validation_start_index)
            & (frame[period_col] <= origin.validation_end_index)
        ].sort_values(period_col)
        if validation.empty:
            continue
        resolution = resolve_seasonal_period(train[target_col], profile=profile)
        forecasts = forecast_all_baselines(
            train[target_col].tolist(),
            len(validation),
            seasonal_period=resolution.period,
        )
        actuals = pd.to_numeric(validation[target_col], errors="coerce").tolist()

        for method_id, baseline in forecasts.items():
            evaluation = results.setdefault(
                method_id,
                ModelEvaluation(
                    model_id=method_id,
                    display_name=baseline.display_name,
                    status=ModelRunStatus.COMPLETED,
                    evaluation_mode=EvaluationMode.ROLLING_ORIGIN
                    if len(origins) > 1
                    else EvaluationMode.HOLDOUT_FALLBACK,
                ),
            )
            origin_result = OriginResult(
                origin_name=origin.name,
                fold_index=origin.fold_index,
                train_end_period=origin.train_end_period,
                train_rows=len(train),
                status=ModelRunStatus.COMPLETED,
                seasonal_period=resolution.period,
                periods=[
                    index_to_period(int(p)) for p in validation[period_col].tolist()
                ],
                horizons=[
                    origin.horizon_of(int(p)) or 0 for p in validation[period_col].tolist()
                ],
                actuals=actuals,
                predictions=list(baseline.values),
                failure_reason=baseline.fallback_reason,
            )
            origin_result.metrics = evaluate(
                actuals,
                baseline.values,
                insample_actuals=train[target_col].tolist(),
                seasonal_period=resolution.period,
            )
            origin_result.legacy_metrics = reference_metrics(actuals, baseline.values)
            evaluation.origins.append(origin_result)

    for evaluation in results.values():
        _finalise(evaluation, frame, period_col=period_col, target_col=target_col)
    return results


def backtest_all_models(
    frame: pd.DataFrame,
    origins: Sequence[Origin],
    *,
    model_ids: Iterable[str] | None = None,
    period_col: str = "period_index",
    target_col: str = "target",
    censored_col: str | None = None,
    base_context: ModelContext | None = None,
    exog_columns: Sequence[str] = (),
    segment: str = "unknown",
    residual_store: ResidualStore | None = None,
    budget: EvaluationBudget | None = None,
) -> dict[str, ModelEvaluation]:
    """Every registered model, in registry order, each isolated from the others.

    Returns one entry per requested model **always** - including models that
    were ineligible, failed, timed out or were never reached. A caller can
    therefore render a complete leaderboard without knowing which models ran.
    """
    from app.ml.registry.canonical_models import CANONICAL_MODEL_IDS
    from app.ml.registry.model_registry import MODEL_REGISTRY

    requested = tuple(model_ids) if model_ids is not None else CANONICAL_MODEL_IDS
    results: dict[str, ModelEvaluation] = {}

    for model_id in requested:
        adapter_cls = MODEL_REGISTRY[model_id]
        try:
            results[model_id] = backtest_model(
                frame,
                lambda context, cls=adapter_cls: cls(context),
                origins,
                period_col=period_col,
                target_col=target_col,
                censored_col=censored_col,
                base_context=base_context,
                exog_columns=exog_columns,
                segment=segment,
                residual_store=residual_store,
                budget=budget,
            )
        except Exception as exc:  # noqa: BLE001 - one model must never stop the rest
            results[model_id] = ModelEvaluation(
                model_id=model_id,
                display_name=adapter_cls.display_name,
                status=ModelRunStatus.FAILED,
                evaluation_mode=EvaluationMode.HOLDOUT_FALLBACK,
                reason=f"{type(exc).__name__}: {exc}"[:500],
            )
    return results
