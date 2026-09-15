"""Training orchestration.

One run walks the tiers in order - `aggregate`, then `local`, then `pooled` -
and for every (scope, model) pair it asked about it writes exactly one
`model_run` row. Including the ones that were ineligible, failed, timed out, or
were never reached. That is the whole point of the table: a leaderboard query
cannot accidentally omit a model, because there is nothing to omit.

Guarantees this module is responsible for:

- **No long work in a request.** Submission returns a run id; the work happens
  in the job runner (`docs/ARCHITECTURE.md` §8).
- **The estimate is shown before the run starts** and stored beside the actual
  duration, so it can be audited rather than forgotten.
- **Cancellation is honoured between scopes**, and a cancelled run keeps the
  rows it already wrote. A partial run that says it is partial is more useful
  than a run that deletes its own evidence.
- **One model's failure never stops another**, and one *scope's* failure never
  stops the next. Both are caught at their own level.
- **Residuals are pooled across the whole run** before quantile cells are
  written, because a per-series calibration would have at most twelve
  residuals (`docs/MODEL_INVENTORY.md` §3).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.domain.ais.backtest_runner import (
    CENSORED_COL,
    PERIOD_COL,
    SERIES_COL,
    TARGET_COL,
    panel_target_source_mix,
    resolve_origins,
)
from app.domain.ais.exog_features import prepare_local_series_frame
from app.domain.ais.scope_builder import (
    AGGREGATE_VAR_PAIR_COLUMN,
    ScopePlan,
    ScopeSeries,
    build_aggregate_plan,
    build_local_plan,
    restrict_panel,
)
from app.jobs.runner import CancellationToken, JobCancelled, get_runner
from app.ml.adapters.base import ModelContext
from app.ml.evaluation.backtest import (
    EvaluationBudget,
    ModelEvaluation,
    backtest_all_models,
    backtest_baselines,
)
from app.ml.evaluation.folds import Origin
from app.ml.evaluation.quantiles import ResidualStore
from app.ml.evaluation.segmentation import profile_series
from app.ml.registry.canonical_models import (
    BASELINE_METHOD_IDS,
    CANONICAL_MODEL_IDS,
)
from app.models.panel import PanelBuild
from app.models.training import ModelRun, QuantileCalibration, TrainingRun
from app.schemas.common import ModelRunStatus
from app.services.training.cost_model import (
    RunEstimate,
    estimate_pooled_tier,
    estimate_tier,
)
from app.services.training.hard_timeout import DEFAULT_HARD_TIMEOUT_MODELS
from app.services.training.pooled import PooledResult, run_pooled_tier
from app.services.training.tracking import tracking_run

logger = get_logger(__name__)

#: Tiers, in the only order they make sense in: cheapest and most aggregated
#: first, so a run that is cancelled early still produced something usable.
TIER_ORDER: tuple[str, ...] = ("aggregate", "local", "pooled")

#: Panel columns the evaluation path needs. Read explicitly rather than loading
#: the whole 41-column panel, and deliberately excluding every PII-adjacent
#: column - there are none in the panel, and this list is where that stays true.
PANEL_COLUMNS: tuple[str, ...] = (
    SERIES_COL,
    PERIOD_COL,
    "period",
    TARGET_COL,
    "despatched_qty",
    "shortfall_qty",
    "mean_mrp",
    CENSORED_COL,
    "target_source",
    "is_materialised",
    "canonical_branch",
    "canonical_sku",
    "region",
    "zone",
    "value_class",
    "product_group",
)


# ----------------------------------------------------------------------
# Estimation
# ----------------------------------------------------------------------


def estimate_run(
    db: Session,
    *,
    panel_build_id: str,
    tiers: Sequence[str],
    max_local_series: int,
    hard_timeout_models: Iterable[str] = (),
) -> RunEstimate:
    """What the run will cost, computed from the panel's real shape.

    Called by the API before submission so nobody starts a three-hour run by
    accident, and again at submission so the number stored on the run is the
    number that was shown.
    """
    build = _require_build(db, panel_build_id)
    settings = get_settings()
    origins = _origin_count(build)
    fast = _fast_holdout_models()

    estimate = RunEstimate(workers=settings.max_training_workers)
    for tier in _ordered(tiers):
        if tier == "aggregate":
            estimate.tiers.append(
                estimate_tier(
                    "aggregate",
                    series=_aggregate_series_count(build),
                    origins=origins,
                    fast_holdout_models=fast,
                    hard_timeout_models=hard_timeout_models,
                )
            )
        elif tier == "local":
            estimate.tiers.append(
                estimate_tier(
                    "local",
                    series=min(max_local_series, build.series_count),
                    origins=origins,
                    fast_holdout_models=fast,
                    hard_timeout_models=hard_timeout_models,
                )
            )
        elif tier == "pooled":
            estimate.tiers.append(
                estimate_pooled_tier(
                    training_rows=build.training_rows,
                    scoring_rows=build.scoring_rows,
                    origins=origins,
                )
            )
    return estimate


# ----------------------------------------------------------------------
# Submission
# ----------------------------------------------------------------------


def start_run(
    db: Session,
    *,
    panel_build_id: str,
    tiers: Sequence[str],
    min_history_profile: str | None = None,
    xgboost_training_profile: str | None = None,
    max_local_series: int | None = None,
    local_series_selection: str | None = None,
    branches: Sequence[str] | None = None,
    skus: Sequence[str] | None = None,
    max_skus: int | None = None,
    total_budget_seconds: float | None = None,
    per_model_timeout_seconds: float | None = None,
    hard_timeout_models: Iterable[str] | None = None,
) -> TrainingRun:
    """Create the run row and hand the work to the job runner."""
    build = _require_build(db, panel_build_id)
    settings = get_settings()
    resolved_tiers = _ordered(tiers)
    if not resolved_tiers:
        raise ConflictError(
            "No valid tier was requested.",
            remediation=f"Choose at least one of {list(TIER_ORDER)}.",
        )
    if _has_active_run(db):
        raise ConflictError(
            "A training run is already in progress.",
            remediation="Wait for it to finish, or cancel it first.",
        )

    hard = sorted(set(hard_timeout_models or DEFAULT_HARD_TIMEOUT_MODELS))
    local_count = (
        settings.max_local_series if max_local_series is None else max_local_series
    )
    estimate = estimate_run(
        db,
        panel_build_id=panel_build_id,
        tiers=resolved_tiers,
        max_local_series=local_count,
        hard_timeout_models=hard,
    )

    run = TrainingRun(
        panel_build_id=build.id,
        status="queued",
        stage_detail="Queued",
        tiers=",".join(resolved_tiers),
        min_history_profile=min_history_profile or settings.min_history_profile,
        xgboost_training_profile=(
            xgboost_training_profile or settings.xgboost_training_profile
        ),
        max_local_series=local_count,
        local_series_selection=(
            local_series_selection or settings.local_series_selection
        ),
        estimated_seconds=estimate.seconds,
        estimate_json={**estimate.as_dict(), "hard_timeout_models": hard},
        # Requested here; the *applied* counts are written back once the panel
        # is loaded and the restriction has actually been measured against it.
        restriction_json=(
            {
                "branches_requested": [str(b) for b in branches] if branches else None,
                "skus_requested": [str(x) for x in skus] if skus else None,
                "max_skus": max_skus,
                "applied": False,
            }
            if branches or skus or max_skus
            else None
        ),
        total_budget_seconds=total_budget_seconds,
        per_model_timeout_seconds=(
            settings.per_model_timeout_seconds
            if per_model_timeout_seconds is None
            else per_model_timeout_seconds
        ),
        lstm_timeout_seconds=settings.lstm_timeout_seconds,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    get_runner().submit(run.id, "training", _run_training_job, run.id)
    return run


def get_run(db: Session, run_id: str) -> TrainingRun:
    run = db.get(TrainingRun, run_id)
    if run is None:
        raise NotFoundError(f"No training run with id {run_id!r}.")
    return run


def list_runs(db: Session, *, offset: int, limit: int) -> tuple[list[TrainingRun], int]:
    total = db.scalar(select(func.count()).select_from(TrainingRun)) or 0
    rows = list(
        db.scalars(
            select(TrainingRun)
            .order_by(TrainingRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


def cancel_run(db: Session, run_id: str) -> TrainingRun:
    run = get_run(db, run_id)
    if run.status in {"completed", "failed", "cancelled"}:
        raise ConflictError(
            f"The run is already {run.status!r}.",
            remediation="Submit a new run instead.",
        )
    get_runner().cancel(run_id)
    run.status = "cancelling"
    run.stage_detail = "Cancellation requested"
    db.commit()
    db.refresh(run)
    return run


def model_runs_for(
    db: Session,
    run_id: str,
    *,
    tier: str | None = None,
    scope_level: str | None = None,
    scope_key: str | None = None,
    include_baselines: bool = True,
    offset: int = 0,
    limit: int = 200,
) -> tuple[list[ModelRun], int]:
    """Per-model rows for a run. Never filters by status.

    A caller asking "what happened in this run" must be able to see the
    ineligible and failed rows; filtering them out is the caller's decision to
    make explicitly, not a default.
    """
    conditions = [ModelRun.training_run_id == run_id]
    if tier:
        conditions.append(ModelRun.tier == tier)
    if scope_level:
        conditions.append(ModelRun.scope_level == scope_level)
    if scope_key:
        conditions.append(ModelRun.scope_key == scope_key)
    if not include_baselines:
        conditions.append(ModelRun.is_baseline.is_(False))

    total = (
        db.scalar(select(func.count()).select_from(ModelRun).where(*conditions)) or 0
    )
    rows = list(
        db.scalars(
            select(ModelRun)
            .where(*conditions)
            .order_by(
                ModelRun.tier,
                ModelRun.scope_level,
                ModelRun.scope_key,
                ModelRun.id,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


# ----------------------------------------------------------------------
# The job
# ----------------------------------------------------------------------


def _run_training_job(run_id: str, *, token: CancellationToken) -> None:
    settings = get_settings()
    started_at = time.perf_counter()

    def progress(stage: str, pct: float) -> None:
        token.raise_if_cancelled()
        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            if run is not None:
                run.status = "running"
                run.stage_detail = stage[:300]
                run.progress_pct = round(pct, 2)

    with session_scope() as db:
        run = db.get(TrainingRun, run_id)
        if run is None:
            return
        build = db.get(PanelBuild, run.panel_build_id)
        artifacts = dict(build.artifacts_json or {}) if build else {}
        config = {
            "tiers": run.tiers.split(","),
            "min_history_profile": run.min_history_profile,
            "xgboost_training_profile": run.xgboost_training_profile,
            "max_local_series": run.max_local_series,
            "local_series_selection": run.local_series_selection,
            "restriction": dict(run.restriction_json or {}),
            "total_budget_seconds": run.total_budget_seconds,
            "per_model_timeout_seconds": run.per_model_timeout_seconds,
            "hard_timeout_models": list(
                (run.estimate_json or {}).get("hard_timeout_models", [])
            ),
            # Carried into the job so the summary can compare the estimate
            # against the actual duration. Reading it from a key that was never
            # set stored 0.0 on every run, which silently defeated the whole
            # point of keeping the two side by side.
            "estimated_seconds": run.estimated_seconds,
        }
        run.status = "running"
        run.stage_detail = "Loading panel"
        run.started_at = datetime.now(timezone.utc)

    warnings: list[str] = []
    artifact_dir = settings.runtime_dir / "storage" / "models" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    try:
        panel_path = artifacts.get("panel")
        if not panel_path:
            raise ConflictError(
                "The panel build recorded no panel artifact.",
                remediation="Rebuild the panel, then submit training again.",
            )
        progress("Loading panel", 2.0)
        panel = pd.read_parquet(panel_path, columns=list(PANEL_COLUMNS))

        # Restriction first, so origins, plans, cost and every count below
        # describe the slice that is actually trained rather than the panel it
        # was cut from.
        requested = config["restriction"]
        if (
            requested.get("branches_requested")
            or requested.get("skus_requested")
            or requested.get("max_skus")
        ):
            panel, restriction = restrict_panel(
                panel,
                branches=requested.get("branches_requested"),
                skus=requested.get("skus_requested"),
                max_skus=requested.get("max_skus"),
                measure=config["local_series_selection"] or "value",
            )
            restriction["applied"] = True
            if panel.empty:
                raise ConflictError(
                    "The requested branch and SKU restriction leaves no data.",
                    remediation=(
                        "Check the branch names against GET /api/analytics/filters, "
                        "or raise max_skus."
                    ),
                )
            warning = restriction.get("scope_warning")
            if warning:
                warnings.append(warning)
            warnings.extend(restriction.get("notes", []))
            with session_scope() as db:
                run = db.get(TrainingRun, run_id)
                if run is not None:
                    run.restriction_json = restriction
        else:
            restriction = {}

        origins = resolve_origins(panel)
        if not origins:
            raise ConflictError(
                "The panel supports no origin with enough training history.",
                remediation=(
                    "A rolling origin needs at least 12 training months and a full "
                    "six-month validation window. Extend the panel or lower the "
                    "horizon."
                ),
            )

        store = ResidualStore()
        totals = {
            "completed": 0,
            "ineligible": 0,
            "failed": 0,
            "timed_out": 0,
            "not_evaluated_budget": 0,
        }
        series_evaluated = 0
        model_rows = 0

        with tracking_run(
            run_name=f"training-{run_id[:8]}",
            tags={
                "panel_build_id": config.get("panel_build_id", ""),
                "tiers": ",".join(config["tiers"]),
                "min_history_profile": config["min_history_profile"],
            },
        ) as tracker:
            tracker.log_params(
                {
                    "tiers": ",".join(config["tiers"]),
                    "min_history_profile": config["min_history_profile"],
                    "xgboost_training_profile": config["xgboost_training_profile"],
                    "max_local_series": config["max_local_series"],
                    "origins": len(origins),
                    "hard_timeout_models": ",".join(config["hard_timeout_models"]) or "none",
                }
            )
            warnings.extend(tracker.warnings)

            plans = _build_plans(panel, config, progress)
            budget = EvaluationBudget(
                total_seconds=config["total_budget_seconds"],
                per_model_seconds=config["per_model_timeout_seconds"],
            )

            scope_total = sum(plan.count for plan in plans) or 1
            done = 0
            for plan in plans:
                for scope in plan.series:
                    token.raise_if_cancelled()
                    done += 1
                    progress(
                        f"{plan.tier}: {scope.scope_key} "
                        f"({done}/{scope_total})",
                        5.0 + 80.0 * done / scope_total,
                    )
                    try:
                        rows, counts = _evaluate_scope(
                            run_id=run_id,
                            tier=plan.tier,
                            scope=scope,
                            origins=origins,
                            config=config,
                            store=store,
                            budget=budget,
                            artifact_dir=artifact_dir,
                            tracker=tracker,
                        )
                    except JobCancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001 - one scope must not stop the rest
                        warnings.append(
                            f"{plan.tier}/{scope.scope_key}: "
                            f"{type(exc).__name__}: {exc}"[:300]
                        )
                        logger.exception(
                            "scope_failed",
                            extra={"tier": plan.tier, "scope": scope.scope_key},
                        )
                        continue
                    series_evaluated += 1
                    model_rows += rows
                    for key, value in counts.items():
                        totals[key] = totals.get(key, 0) + value

            pooled: PooledResult | None = None
            if "pooled" in config["tiers"]:
                progress("pooled tier: fitting the global model", 88.0)
                try:
                    pooled = run_pooled_tier(
                        artifacts=artifacts,
                        origins=origins,
                        run_id=run_id,
                        profile=config["min_history_profile"],
                        xgboost_profile=config["xgboost_training_profile"],
                        artifact_dir=artifact_dir,
                        store=store,
                        token=token,
                    )
                    with session_scope() as db:
                        for row in pooled.model_rows:
                            db.add(ModelRun(training_run_id=run_id, **row))
                            model_rows += 1
                            status = str(row.get("status"))
                            totals[status] = totals.get(status, 0) + 1
                    warnings.extend(pooled.warnings)
                    tracker.log_metrics(
                        {f"pooled_{k}": v for k, v in (pooled.metrics or {}).items()}
                    )
                except JobCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"pooled tier failed: {type(exc).__name__}: {exc}"[:300])
                    logger.exception("pooled_tier_failed")

            progress("Calibrating quantiles", 94.0)
            calibration_rows = _write_calibrations(run_id, store)
            warnings.extend(tracker.warnings)
            mlflow_run_id = tracker.run_id

        progress("Finalising", 98.0)
        duration = time.perf_counter() - started_at
        summary = {
            "origins": [origin.as_dict() for origin in origins],
            "restriction": restriction or None,
            "window_composition": panel_target_source_mix(panel, origins),
            "scope_plans": [plan.as_dict() for plan in plans],
            "calibration_cells": calibration_rows,
            "residuals": store.total(),
            "pooled": None if pooled is None else pooled.summary,
            "estimate_vs_actual": {
                "estimated_seconds": round(
                    float(config.get("estimated_seconds") or 0.0), 1
                ),
                "actual_seconds": round(duration, 1),
            },
        }
        manifest = artifact_dir / "training_manifest.json"
        manifest.write_text(
            json.dumps({"training_run_id": run_id, **summary}, indent=2, default=str),
            encoding="utf-8",
        )

        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            if run is None:
                return
            run.status = "completed_with_warnings" if warnings else "completed"
            run.stage_detail = "Complete"
            run.progress_pct = 100.0
            run.finished_at = datetime.now(timezone.utc)
            run.duration_seconds = round(duration, 2)
            run.series_requested = sum(plan.count for plan in plans)
            run.series_evaluated = series_evaluated
            run.model_runs_total = model_rows
            run.model_runs_completed = totals.get("completed", 0)
            run.model_runs_ineligible = totals.get("ineligible", 0)
            run.model_runs_failed = totals.get("failed", 0)
            run.model_runs_timed_out = totals.get("timed_out", 0)
            run.model_runs_not_evaluated = totals.get("not_evaluated_budget", 0)
            run.residuals_recorded = store.total()
            run.mlflow_run_id = mlflow_run_id
            run.artifact_dir = str(artifact_dir)
            run.origins_json = {
                "origins": [origin.as_dict() for origin in origins],
                "window_composition": summary["window_composition"],
            }
            run.summary_json = summary
            run.warnings_json = warnings or None

    except JobCancelled:
        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            if run is not None:
                run.status = "cancelled"
                run.stage_detail = "Cancelled"
                run.cancelled_at = datetime.now(timezone.utc)
                run.finished_at = datetime.now(timezone.utc)
                run.duration_seconds = round(time.perf_counter() - started_at, 2)
                # Rows already written are kept on purpose: a partial run that
                # says it is partial beats one that destroys its own evidence.
                run.warnings_json = (run.warnings_json or []) + [
                    "cancelled mid-run; the model_run rows already written are "
                    "retained and cover only the scopes completed before "
                    "cancellation"
                ]
    except Exception as exc:  # noqa: BLE001
        logger.exception("training_run_failed", extra={"run_id": run_id})
        with session_scope() as db:
            run = db.get(TrainingRun, run_id)
            if run is not None:
                run.status = "failed"
                run.stage_detail = "Failed"
                run.finished_at = datetime.now(timezone.utc)
                run.duration_seconds = round(time.perf_counter() - started_at, 2)
                run.failure_reason = f"{type(exc).__name__}: {exc}"[:1000]
                run.warnings_json = warnings or None


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _build_plans(
    panel: pd.DataFrame, config: dict[str, Any], progress: Any
) -> list[ScopePlan]:
    plans: list[ScopePlan] = []
    if "aggregate" in config["tiers"]:
        progress("Building aggregate scopes", 3.0)
        plans.append(build_aggregate_plan(panel))
    if "local" in config["tiers"]:
        progress("Selecting high-value series", 4.0)
        plans.append(
            build_local_plan(
                panel,
                max_series=int(config["max_local_series"]),
                measure=str(config["local_series_selection"] or "value"),
            )
        )
    return plans


def _evaluate_scope(
    *,
    run_id: str,
    tier: str,
    scope: ScopeSeries,
    origins: Sequence[Origin],
    config: dict[str, Any],
    store: ResidualStore,
    budget: EvaluationBudget,
    artifact_dir: Path,
    tracker: Any,
) -> tuple[int, dict[str, int]]:
    """Evaluate one scope's 13 models plus baselines, and persist the rows."""
    frame, exog_columns = prepare_local_series_frame(scope.frame, period_col=PERIOD_COL)
    sparsity = profile_series(scope.frame[TARGET_COL])

    context = ModelContext(
        exog_columns=exog_columns,
        min_history_profile=str(config["min_history_profile"]),
        xgboost_training_profile=str(config["xgboost_training_profile"]),
        # An aggregate scope has no usable `despatched_qty` - it is null on
        # every sales-proxy member, so strict aggregation makes it null - and
        # would leave VAR with one endogenous series. `active_cells` is the
        # honest pair at that level (D-042).
        var_pair_column=(
            AGGREGATE_VAR_PAIR_COLUMN if scope.scope_level != "series" else "despatched_qty"
        ),
    )

    evaluations = backtest_all_models(
        frame,
        origins,
        period_col=PERIOD_COL,
        target_col=TARGET_COL,
        censored_col=CENSORED_COL,
        base_context=context,
        exog_columns=exog_columns,
        segment=sparsity.segment.value,
        residual_store=store,
        budget=budget,
    )
    baselines = backtest_baselines(
        frame,
        origins,
        period_col=PERIOD_COL,
        target_col=TARGET_COL,
        profile=str(config["min_history_profile"]),
    )

    counts: dict[str, int] = {}
    rows = 0
    with session_scope() as db:
        for model_id in CANONICAL_MODEL_IDS:
            evaluation = evaluations.get(model_id)
            if evaluation is None:
                continue
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    **_model_run_fields(
                        tier=tier,
                        scope=scope,
                        segment=sparsity.segment.value,
                        evaluation=evaluation,
                        is_baseline=False,
                    ),
                )
            )
            rows += 1
            counts[evaluation.status.value] = counts.get(evaluation.status.value, 0) + 1
            _log_evaluation(tracker, tier, scope, evaluation)

        for method_id in BASELINE_METHOD_IDS:
            evaluation = baselines.get(method_id)
            if evaluation is None:
                continue
            db.add(
                ModelRun(
                    training_run_id=run_id,
                    **_model_run_fields(
                        tier=tier,
                        scope=scope,
                        segment=sparsity.segment.value,
                        evaluation=evaluation,
                        is_baseline=True,
                    ),
                )
            )
            rows += 1
            # Counted here as well as `rows`. Omitting this made
            # `model_runs_total` include the four baselines while
            # `model_runs_completed` excluded them, so a 49-scope run reported
            # 833 total against 623 completed and the 196 baseline rows read as
            # having silently disappeared - which is precisely the failure the
            # status vocabulary exists to prevent. A baseline is not a
            # candidate, but it did run and its outcome is a fact.
            counts[evaluation.status.value] = counts.get(evaluation.status.value, 0) + 1
    return rows, counts


def _model_run_fields(
    *,
    tier: str,
    scope: ScopeSeries,
    segment: str,
    evaluation: ModelEvaluation,
    is_baseline: bool,
) -> dict[str, Any]:
    """Flatten one evaluation into `model_run` columns.

    Metrics stay `None` where the metric is undefined - never 0, never a
    sentinel. `legacy_valid` records whether the row would have entered the
    references' own MAPE ranking, which on intermittent data is usually False
    (D-011).
    """
    from app.ml.evaluation.metrics import is_valid_metric

    pooled = evaluation.pooled
    legacy = evaluation.pooled_legacy or {}
    completed = evaluation.completed_origins
    latest = max(completed, key=lambda o: o.fold_index) if completed else None

    return {
        "tier": tier,
        "scope_level": scope.scope_level,
        "scope_key": scope.scope_key,
        "segment": segment,
        "model_id": evaluation.model_id,
        "display_name": evaluation.display_name,
        "is_baseline": is_baseline,
        "status": evaluation.status.value,
        "evaluation_mode": evaluation.evaluation_mode.value,
        "failure_reason": evaluation.reason,
        "eligibility_json": (
            evaluation.origins[0].eligibility.as_dict()
            if evaluation.origins and evaluation.origins[0].eligibility
            else None
        ),
        "seasonal_period": latest.seasonal_period if latest else None,
        "origins_completed": len(completed),
        "origins_total": len(evaluation.origins),
        "validation_points": pooled.points if pooled else 0,
        "total_test_points": evaluation.total_test_points,
        "duplicate_test_points": evaluation.duplicate_test_points,
        "mae": pooled.mae if pooled else None,
        "rmse": pooled.rmse if pooled else None,
        "wape": pooled.wape if pooled else None,
        "mape": pooled.mape if pooled else None,
        "accuracy": pooled.accuracy if pooled else None,
        "smape": pooled.smape if pooled else None,
        "mase": pooled.mase if pooled else None,
        "bias": pooled.bias if pooled else None,
        "bias_abs": pooled.bias_abs if pooled else None,
        "naive_mae": pooled.naive_mae if pooled else None,
        "legacy_mape": legacy.get("mape"),
        "legacy_wape": legacy.get("wape"),
        "legacy_mae": legacy.get("mae"),
        "legacy_valid": bool(
            is_valid_metric({**legacy, "status": evaluation.status.value})
        ),
        "zero_actual_points": pooled.zero_actual_points if pooled else 0,
        "censored_points": pooled.censored_points if pooled else 0,
        "negative_predictions": sum(o.negative_predictions for o in evaluation.origins),
        "max_abs_prediction": max(
            (o.max_abs_prediction for o in evaluation.origins if o.max_abs_prediction),
            default=None,
        ),
        "fit_seconds": sum(o.fit_seconds or 0.0 for o in completed) or None,
        "predict_seconds": sum(o.predict_seconds or 0.0 for o in completed) or None,
        "origins_json": [o.as_dict() for o in evaluation.origins],
    }


def _log_evaluation(
    tracker: Any, tier: str, scope: ScopeSeries, evaluation: ModelEvaluation
) -> None:
    """Only aggregate scopes are logged per model to MLflow.

    69 aggregate scopes x 13 models is 897 metric sets, which MLflow handles
    comfortably. 500 local scopes would be another 6,500, and an experiment
    that large is slower to open than it is useful. The database has all of
    them either way, which is why this can be a presentation decision.
    """
    if not tracker.available or scope.scope_level == "series":
        return
    if evaluation.pooled is None:
        return
    prefix = f"{tier}.{scope.scope_level}.{evaluation.model_id}"
    tracker.log_metrics(
        {
            f"{prefix}.wape": evaluation.pooled.wape,
            f"{prefix}.mae": evaluation.pooled.mae,
            f"{prefix}.mase": evaluation.pooled.mase,
        }
    )


def _write_calibrations(run_id: str, store: ResidualStore) -> int:
    """One row per (model, horizon, segment) cell that has residuals."""
    written = 0
    with session_scope() as db:
        for model_id, horizon, segment in store.cells():
            calibration = store.calibrate(model_id, horizon, segment)
            offsets = {key: value.as_dict() for key, value in calibration.offsets.items()}
            levels = list(calibration.offsets.values())
            db.add(
                QuantileCalibration(
                    training_run_id=run_id,
                    model_id=model_id,
                    horizon=horizon,
                    segment=segment,
                    residual_count=store.count(model_id, horizon, segment),
                    offsets_json=offsets,
                    # The coarsest level anything in this cell fell back to, so
                    # a reader sees the weakest link rather than the best one.
                    pooling_level=_coarsest(levels),
                    method=_weakest_method(levels),
                )
            )
            written += 1
    return written


def _coarsest(levels: Sequence[Any]) -> str | None:
    from app.ml.evaluation.quantiles import POOLING_LEVELS

    order = {name: index for index, name in enumerate(POOLING_LEVELS)}
    seen = [level.pooling_level for level in levels if level.pooling_level in order]
    return max(seen, key=lambda name: order[name]) if seen else None


def _weakest_method(levels: Sequence[Any]) -> str | None:
    methods = {level.method for level in levels}
    for candidate in ("none", "empirical", "conformal"):
        if candidate in methods:
            return candidate
    return None


def _require_build(db: Session, panel_build_id: str) -> PanelBuild:
    build = db.get(PanelBuild, panel_build_id)
    if build is None:
        raise NotFoundError(f"No panel build with id {panel_build_id!r}.")
    if build.status != "completed":
        raise ConflictError(
            f"The panel build is {build.status!r}, not completed.",
            remediation="Wait for the panel build to finish, then submit training.",
        )
    return build


def _has_active_run(db: Session) -> bool:
    active = db.scalars(
        select(TrainingRun).where(
            TrainingRun.status.in_(("queued", "running", "cancelling"))
        )
    ).all()
    return any(get_runner().is_running(run.id) for run in active)


def _ordered(tiers: Iterable[str]) -> list[str]:
    requested = {tier.strip().lower() for tier in tiers if tier}
    return [tier for tier in TIER_ORDER if tier in requested]


def _origin_count(build: PanelBuild) -> int:
    """How many origins the panel supports, without loading it.

    `period_count` is on the build row, so the estimate does not have to read
    1.5 M rows of parquet to answer "how long will this take".
    """
    from app.ml.evaluation.folds import DEFAULT_HORIZON, MIN_TRAIN_PERIODS

    usable = build.period_count - MIN_TRAIN_PERIODS
    if usable < DEFAULT_HORIZON:
        return 0
    return min(2, usable // DEFAULT_HORIZON)


def _aggregate_series_count(build: PanelBuild) -> int:
    """Measured on the real panel: 1 national + 6 regions + 53 branches + 9
    segments = 69. Read from the build's summary when it recorded them, so a
    differently shaped panel is estimated from its own shape."""
    summary = build.summary_json or {}
    recorded = summary.get("aggregate_scope_count")
    return int(recorded) if recorded else 69


def _fast_holdout_models() -> set[str]:
    from app.ml.registry.model_registry import MODEL_REGISTRY

    return {
        model_id
        for model_id, adapter in MODEL_REGISTRY.items()
        if adapter.uses_fast_holdout
    }


def reconcile_orphaned_runs() -> int:
    """Close out runs the previous process was executing when it stopped.

    The job runner is in-process (`docs/DECISIONS.md` D-007), so a restart -
    a deploy, a crash, Ctrl-C - leaves any in-flight run's row saying
    `running` with nothing running it. Nothing else notices: the row is only
    ever updated by the worker that owned it, and that worker is gone.

    That is a status lie, and status is load-bearing here. A page showing a
    spinner for a run that will never finish is worse than one showing a
    failure, because the failure at least tells the reader to resubmit.

    So at startup every run still in a live state is marked `failed` with the
    reason, and the `model_run` rows it already wrote are **kept** - same
    reasoning as cancellation: a partial run that says it is partial is
    evidence, and deleting it destroys the only record of what did complete.

    **The counters are backfilled from those rows.** Only the owning worker
    writes them, at completion, so an orphaned run used to report
    `model_runs_total = 0` while its own `failure_reason` on the same record
    said it had written 2,227 - a row contradicting itself, and a Training
    Center showing "0 model runs" for a run that produced thousands. Everything
    recoverable is recovered here; `series_requested` and `residuals_recorded`
    are not, because they come from the in-memory plan and residual store which
    died with the process (docs/DECISIONS.md D-053).

    Returns how many rows were reconciled, for the startup log.
    """
    live = ("queued", "running", "cancelling")
    reconciled = 0
    with session_scope() as db:
        runs = list(db.scalars(select(TrainingRun).where(TrainingRun.status.in_(live))))
        for run in runs:
            # One grouped read rather than a count per status: the same rows
            # answer every counter, and the total is their sum.
            by_status = dict(
                db.execute(
                    select(ModelRun.status, func.count())
                    .where(ModelRun.training_run_id == run.id)
                    .group_by(ModelRun.status)
                ).all()
            )
            written = sum(by_status.values())
            # A "series" here is a scope, matching what the completion path
            # counts - distinct (level, key) pairs, not distinct model rows.
            scopes = (
                db.scalar(
                    select(func.count()).select_from(
                        select(ModelRun.scope_level, ModelRun.scope_key)
                        .where(ModelRun.training_run_id == run.id)
                        .distinct()
                        .subquery()
                    )
                )
                or 0
            )

            previous = run.status
            run.status = "failed"
            run.stage_detail = "Interrupted"
            finished = datetime.now(timezone.utc)
            run.finished_at = finished

            run.model_runs_total = written
            run.model_runs_completed = by_status.get("completed", 0)
            run.model_runs_ineligible = by_status.get("ineligible", 0)
            run.model_runs_failed = by_status.get("failed", 0)
            run.model_runs_timed_out = by_status.get("timed_out", 0)
            run.model_runs_not_evaluated = by_status.get("not_evaluated_budget", 0)
            run.series_evaluated = scopes

            # Both timestamps are already on the row, so a null duration was
            # a subtraction nobody performed. SQLite hands back naive
            # datetimes, so normalise before subtracting or this raises.
            if run.started_at is not None:
                started = run.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                run.duration_seconds = round((finished - started).total_seconds(), 2)

            run.failure_reason = (
                "The server process ended while this run was in progress, so it "
                f"was never completed. It had written {written} model_run row(s) "
                f"across {scopes} scope(s), which are retained rather than "
                "deleted - they are the only record of what did finish. There is "
                "no resume: resubmit to run it again from the start."
            )
            run.warnings_json = (run.warnings_json or []) + [
                "reconciled at startup: the owning process was gone, so the "
                f"status was corrected from {previous!r} to 'failed'",
                "counters and duration were rebuilt from the stored model_run "
                "rows; series_requested and residuals_recorded are not "
                "recoverable and stay at 0",
            ]
            reconciled += 1
    return reconciled
