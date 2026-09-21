"""Forecast generation: champion refit, quantiles, reconciliation, persistence.

The pipeline for one run is:

1. Resolve the origin - the last period the panel actually observes - and the
   six future periods after it.
2. For each scope with an **active champion selection**, refit that champion on
   the scope's whole history (not the backtest's training window: a forecast
   served today should use every month that exists) and predict horizons 1-6.
3. Turn each point forecast into q80/q90/q95 using the calibration cells the
   training run persisted, carrying the pooling level and method onto the row.
4. Reconcile the levels per future period, then re-sort the quantiles so
   `point <= q80 <= q90 <= q95` still holds afterwards.
5. Persist one row per (scope, period), including rows that say why no forecast
   was possible.

What this module refuses to do:

**It never invents a forecast.** A scope with no champion, a champion that will
not refit, or a divergent prediction produces a row with a null point forecast
and an `unavailable_reason`. A zero would be indistinguishable from a genuine
zero-demand forecast.

**It never presents a fallback as the champion's own work.** `forecast_source`
distinguishes `champion` from `pooled_fallback` and `baseline_fallback`.

**It never claims coherence it did not verify.** The reconciliation result's own
check is stored, and an incoherent result is recorded as incoherent.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import numpy as np
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
)
from app.domain.ais.deployability import prepare_scope_fit
from app.domain.ais.exog_features import prepare_local_series_frame
from app.domain.ais.scope_builder import (
    SEGMENT_COLUMNS,
    ScopeSeries,
    build_aggregate_plan,
)
from app.jobs.runner import CancellationToken, JobCancelled, get_runner
from app.ml.evaluation.backtest import forecast_magnitude_bound
from app.ml.evaluation.quantiles import (
    MIN_RESIDUALS,
    Calibration,
    QuantileOffset,
    ResidualStore,
    apply_calibration,
    conformal_minimum,
)
from app.ml.evaluation.segmentation import profile_series
from app.ml.reconciliation.mint import (
    Hierarchy,
    build_hierarchy,
    reconcile,
    reconcile_quantiles,
)
from app.ml.registry.model_registry import MODEL_REGISTRY
from app.models.champions import ChampionSelection
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.panel import PanelBuild
from app.models.training import ModelRun, QuantileCalibration, TrainingRun
from app.services.training.training_service import PANEL_COLUMNS

logger = get_logger(__name__)

#: The quantile levels AIS publishes. Outputs of the point forecast, never
#: models in their own right.
QUANTILE_KEYS: tuple[str, ...] = ("q80", "q90", "q95")

#: Default reconciliation per level pair, from `docs/ARCHITECTURE.md` §5.
DEFAULT_RECONCILIATION = "mint_shrinkage"

#: How the scope levels nest.
LEVEL_ORDER: tuple[str, ...] = ("series", "branch", "region", "national")


# ----------------------------------------------------------------------
# Submission
# ----------------------------------------------------------------------


def start_run(
    db: Session,
    *,
    training_run_id: str | None = None,
    reconciliation: str = DEFAULT_RECONCILIATION,
    horizons: Sequence[int] = (1, 2, 3, 4, 5, 6),
) -> ForecastRun:
    """Create the run row and hand generation to the job runner."""
    training = _require_training_run(db, training_run_id)
    if _has_active_run(db):
        raise ConflictError(
            "A forecast run is already in progress.",
            remediation="Wait for it to finish before starting another.",
        )
    champions = db.scalar(
        select(func.count())
        .select_from(ChampionSelection)
        .where(
            ChampionSelection.training_run_id == training.id,
            ChampionSelection.is_active.is_(True),
        )
    )
    if not champions:
        raise ConflictError(
            f"Training run {training.id!r} has no active champion selection, so "
            "there is no model to forecast with.",
            remediation="POST /api/models/champions/select first.",
        )

    build = db.get(PanelBuild, training.panel_build_id)
    if build is None:
        raise NotFoundError(
            f"The panel build behind training run {training.id!r} is missing."
        )

    ordered = tuple(sorted({int(h) for h in horizons if int(h) >= 1}))
    run = ForecastRun(
        training_run_id=training.id,
        panel_build_id=build.id,
        status="queued",
        stage_detail="Queued",
        origin_period="",
        horizons=",".join(str(h) for h in ordered),
        requested_reconciliation=reconciliation,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    get_runner().submit(run.id, "forecast", _run_forecast_job, run.id)
    return run


def get_run(db: Session, run_id: str) -> ForecastRun:
    run = db.get(ForecastRun, run_id)
    if run is None:
        raise NotFoundError(f"No forecast run with id {run_id!r}.")
    return run


def latest_run(db: Session, *, completed_only: bool = True) -> ForecastRun:
    query = select(ForecastRun)
    if completed_only:
        query = query.where(ForecastRun.status == "completed")
    run = db.scalars(query.order_by(ForecastRun.created_at.desc()).limit(1)).first()
    if run is None:
        raise NotFoundError(
            "No completed forecast run exists yet.",
            remediation="POST /api/forecasts/runs to generate one.",
        )
    return run


def list_runs(db: Session, *, offset: int, limit: int) -> tuple[list[ForecastRun], int]:
    total = db.scalar(select(func.count()).select_from(ForecastRun)) or 0
    rows = list(
        db.scalars(
            select(ForecastRun)
            .order_by(ForecastRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


def _require_training_run(db: Session, run_id: str | None) -> TrainingRun:
    if run_id:
        run = db.get(TrainingRun, run_id)
        if run is None:
            raise NotFoundError(f"No training run with id {run_id!r}.")
        return run
    run = db.scalars(
        select(TrainingRun)
        .join(
            ChampionSelection,
            ChampionSelection.training_run_id == TrainingRun.id,
        )
        .where(ChampionSelection.is_active.is_(True))
        .order_by(TrainingRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise NotFoundError(
            "No training run has an active champion selection.",
            remediation="Run training, then POST /api/models/champions/select.",
        )
    return run


def _has_active_run(db: Session) -> bool:
    active = db.scalars(
        select(ForecastRun).where(ForecastRun.status.in_(("queued", "running")))
    ).all()
    return any(get_runner().is_running(run.id) for run in active)


# ----------------------------------------------------------------------
# The job
# ----------------------------------------------------------------------


def _run_forecast_job(run_id: str, *, token: CancellationToken) -> None:
    started = time.perf_counter()

    def progress(stage: str, pct: float) -> None:
        token.raise_if_cancelled()
        with session_scope() as db:
            run = db.get(ForecastRun, run_id)
            if run is not None:
                run.status = "running"
                run.stage_detail = stage[:300]
                run.progress_pct = round(pct, 2)

    try:
        with session_scope() as db:
            run = db.get(ForecastRun, run_id)
            if run is None:
                return
            run.status = "running"
            run.started_at = datetime.now(timezone.utc)
            training_run_id = run.training_run_id
            build_id = run.panel_build_id
            requested = run.requested_reconciliation or DEFAULT_RECONCILIATION
            horizons = tuple(
                int(part) for part in (run.horizons or "1,2,3,4,5,6").split(",") if part
            )

        progress("Loading the panel", 2.0)
        panel = _load_panel(build_id)

        # Cut to the workspace before the scope plan is built.
        #
        # `build_aggregate_plan` derives its scopes from whatever panel it is
        # handed, so an unrestricted panel produced 1 national + 6 regions +
        # 53 branches + 9 segments - and 51 of those branches have no champion
        # and appear on no screen. Worse, the national aggregate then summed
        # 53 branches while only 2 were modelled, so reconciliation was
        # distributing a total across scopes the run did not cover
        # (docs/DECISIONS.md D-058).
        #
        # Restricting here rather than inside `_load_panel` keeps it beside the
        # scope plan it governs, and lets the run record what it covered.
        workspace = resolve_workspace_for_forecast()
        panel = workspace.restrict(panel, "canonical_branch")
        if panel.empty:
            raise ConflictError(
                "The workspace restriction leaves no panel rows to forecast.",
                remediation=(
                    "Check AIS_WORKSPACE_BRANCHES and AIS_WORKSPACE_SKUS against the "
                    "panel, or clear them to forecast the whole network."
                ),
            )
        origin_period = str(panel[["period"]].max().iloc[0])

        progress("Building the scope plan", 8.0)
        with session_scope() as db:
            champions = {
                (selection.scope_kind, selection.scope_key): selection
                for selection in db.scalars(
                    select(ChampionSelection).where(
                        ChampionSelection.training_run_id == training_run_id,
                        ChampionSelection.is_active.is_(True),
                    )
                )
            }
            calibrations = _load_calibrations(db, training_run_id)
            config = _run_config(db, training_run_id)

        # Aggregate scopes, plus every branch x SKU series that has a champion.
        # Forecasting only the aggregate tier would leave a selected series
        # champion unused - and an inventory recommendation is placed per branch
        # x SKU, so the series rows are the ones Phase 10 actually needs.
        scopes = list(build_aggregate_plan(panel).series)
        scopes.extend(_series_scopes(panel, champions))

        results: list[dict[str, Any]] = []
        total = len(scopes)
        for index, scope in enumerate(scopes, start=1):
            token.raise_if_cancelled()
            progress(
                f"Forecasting {scope.scope_level}: {scope.scope_key} ({index}/{total})",
                8.0 + 72.0 * index / max(total, 1),
            )
            results.append(
                _forecast_scope(
                    scope=scope,
                    champions=champions,
                    calibrations=calibrations,
                    config=config,
                    horizons=horizons,
                    origin_period=origin_period,
                )
            )

        progress("Reconciling the hierarchy", 84.0)
        reconciled, recon_meta = _reconcile_results(
            results, panel=panel, method=requested, horizons=horizons
        )

        progress("Persisting forecast rows", 92.0)
        written, unavailable = _persist(run_id, reconciled, origin_period)

        with session_scope() as db:
            run = db.get(ForecastRun, run_id)
            if run is None:
                return
            run.status = "completed"
            run.stage_detail = "Complete"
            run.progress_pct = 100.0
            run.finished_at = datetime.now(timezone.utc)
            run.duration_seconds = round(time.perf_counter() - started, 2)
            run.origin_period = origin_period
            run.reconciliation_method = recon_meta.get("method")
            run.reconciliation_fallback_from = recon_meta.get("fallback_from")
            run.reconciliation_fallback_reason = recon_meta.get("fallback_reason")
            run.shrinkage_intensity = recon_meta.get("shrinkage_intensity")
            run.coherent = bool(recon_meta.get("coherent"))
            run.max_incoherence = recon_meta.get("max_incoherence")
            run.negatives_clipped = int(recon_meta.get("negatives_clipped") or 0)
            run.quantile_crossings_corrected = int(
                recon_meta.get("quantile_crossings_corrected") or 0
            )
            run.series_forecast = sum(
                1 for result in results if result.get("point") is not None
            )
            run.rows_written = written
            run.rows_unavailable = unavailable
            run.summary_json = {
                # Carried so a forecast produced over two branches can never be
                # read as a national one, the same rule every payload follows.
                "workspace_scope": workspace.as_dict(),
                "origin_period": origin_period,
                "forecast_periods": _future_periods(origin_period, horizons),
                "scopes": total,
                "scopes_with_champion": sum(
                    1 for result in results if result.get("model_id")
                ),
                "scopes_unavailable": sum(
                    1 for result in results if result.get("unavailable_reason")
                ),
                # Aggregates with no champion, filled by adding up their parts.
                "scopes_rolled_up": len(recon_meta.get("rolled_up") or []),
                "reconciliation": recon_meta,
                "quantile_provenance": _provenance_summary(results),
            }
            run.warnings_json = recon_meta.get("notes") or []
        logger.info("forecast_run_completed", extra={"run_id": run_id, "rows": written})

    except JobCancelled:
        with session_scope() as db:
            run = db.get(ForecastRun, run_id)
            if run is not None:
                run.status = "cancelled"
                run.stage_detail = "Cancelled"
                run.finished_at = datetime.now(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - the run records its own failure
        logger.exception("forecast_run_failed", extra={"run_id": run_id})
        with session_scope() as db:
            run = db.get(ForecastRun, run_id)
            if run is not None:
                run.status = "failed"
                run.stage_detail = "Failed"
                run.failure_reason = f"{type(exc).__name__}: {exc}"[:2000]
                run.finished_at = datetime.now(timezone.utc)
                run.duration_seconds = round(time.perf_counter() - started, 2)


def resolve_workspace_for_forecast():
    """The workspace scope, on its own session.

    The forecast job runs outside a request, so it opens its own session
    rather than receiving one.
    """
    from app.domain.ais.workspace import resolve_workspace

    with session_scope() as db:
        return resolve_workspace(db)


def _load_panel(build_id: str) -> pd.DataFrame:
    with session_scope() as db:
        build = db.get(PanelBuild, build_id)
        if build is None:
            raise NotFoundError(f"No panel build with id {build_id!r}.")
        artifacts = build.artifacts_json or {}
    path = artifacts.get("panel")
    if not path:
        raise ConflictError(
            "The panel build recorded no panel artifact, so there is nothing to "
            "forecast from.",
            remediation="Rebuild the panel.",
        )
    columns = [column for column in PANEL_COLUMNS]
    return pd.read_parquet(path, columns=columns)


def _run_config(db: Session, training_run_id: str) -> dict[str, Any]:
    run = db.get(TrainingRun, training_run_id)
    settings = get_settings()
    return {
        "min_history_profile": (
            run.min_history_profile if run else settings.min_history_profile
        ),
        "xgboost_training_profile": (
            run.xgboost_training_profile if run else settings.xgboost_training_profile
        ),
        "random_seed": settings.random_seed,
    }


def _load_calibrations(
    db: Session, training_run_id: str
) -> dict[tuple[str, int, str], QuantileCalibration]:
    return {
        (row.model_id, row.horizon, row.segment): row
        for row in db.scalars(
            select(QuantileCalibration).where(
                QuantileCalibration.training_run_id == training_run_id
            )
        )
    }


# ----------------------------------------------------------------------
# One scope
# ----------------------------------------------------------------------


def _scope_identity(scope: ScopeSeries) -> dict[str, Any]:
    """Branch, SKU and region for one scope, read from its own frame.

    Read from the data rather than parsed out of the scope key: the key is a
    label, and a branch whose name contains the separator would defeat a parse.
    """
    frame = scope.frame
    identity: dict[str, Any] = {
        "canonical_branch": None,
        "canonical_sku": None,
        "region": None,
    }
    if scope.scope_level == "branch":
        identity["canonical_branch"] = scope.scope_key
    if scope.scope_level == "region":
        identity["region"] = scope.scope_key
    for column in ("canonical_branch", "canonical_sku", "region"):
        if column not in frame.columns:
            continue
        values = frame[column].dropna().unique()
        # Only a column that is constant across the scope identifies it. A
        # region's forecast has many branches beneath it, and naming one of
        # them would be a lie about what the row covers.
        if len(values) == 1:
            identity[column] = str(values[0])
    return identity


def _series_scopes(
    panel: pd.DataFrame, champions: dict[tuple[str, str], ChampionSelection]
) -> list[ScopeSeries]:
    """One `ScopeSeries` per branch x SKU that has an active champion.

    Built from the champion selections rather than from a top-N rule, so the
    series forecast covers exactly what was evaluated and chosen. A champion
    whose series is no longer in the panel is skipped rather than fabricated -
    the scope then has no forecast row and the reason is recorded.
    """
    keys = [key for kind, key in champions if kind == "series"]
    if not keys or SERIES_COL not in panel.columns:
        return []
    wanted = set(keys)
    subset = panel[panel[SERIES_COL].isin(wanted)]
    output: list[ScopeSeries] = []
    for key, group in subset.groupby(SERIES_COL, observed=True, sort=True):
        output.append(
            ScopeSeries(
                scope_level="series",
                scope_key=str(key),
                frame=group.sort_values(PERIOD_COL).reset_index(drop=True),
                member_series=1,
            )
        )
    return output


def _scope_kind(scope: ScopeSeries) -> str:
    if scope.scope_level == "national":
        return "overall"
    if scope.scope_level == "segment":
        return scope.scope_key.split("=", 1)[0]
    return scope.scope_level


def _forecast_scope(
    *,
    scope: ScopeSeries,
    champions: dict[tuple[str, str], ChampionSelection],
    calibrations: dict[tuple[str, int, str], QuantileCalibration],
    config: dict[str, Any],
    horizons: Sequence[int],
    origin_period: str,
) -> dict[str, Any]:
    """Refit one scope's champion on its whole history and predict forward."""
    kind = _scope_kind(scope)
    result: dict[str, Any] = {
        "scope_level": scope.scope_level,
        "scope_key": scope.scope_key,
        "scope_kind": kind,
        "horizons": list(horizons),
        "periods": _future_periods(origin_period, horizons),
        "point": None,
        "quantiles": {},
        "model_id": None,
        "unavailable_reason": None,
        # Carried so a scope filled by addition can state how many series it
        # added up, without re-deriving the membership it was built from.
        "member_series": scope.member_series,
        # Denormalised onto every row so Phase 10 can join a series forecast to
        # the stock snapshot without re-parsing the scope key, and so the
        # Forecast Explorer can filter without touching the panel.
        **_scope_identity(scope),
    }

    selection = champions.get((kind, scope.scope_key))
    if selection is None:
        result["unavailable_reason"] = (
            f"No active champion is selected for {kind}/{scope.scope_key}, so "
            "no model was available to forecast with. Nothing was substituted."
        )
        return result

    adapter_factory = MODEL_REGISTRY.get(selection.champion_model_id)
    if adapter_factory is None:
        result["unavailable_reason"] = (
            f"{selection.champion_model_id!r} is not in the model registry."
        )
        return result

    # The one definition of what a scope is fitted on, shared with the
    # deployability gate in champion selection: if the two built a different
    # frame or context, the gate would be answering about data that is not this
    # data, and a champion could still be crowned that cannot run here.
    fit = prepare_scope_fit(
        scope.frame,
        scope_level=scope.scope_level,
        horizons=horizons,
        config=config,
    )
    frame, exog_columns, context, seasonal = (
        fit.frame,
        list(fit.exog_columns),
        fit.context,
        fit.seasonal,
    )
    sparsity = profile_series(scope.frame[TARGET_COL])
    result["segment"] = sparsity.segment.value

    adapter = adapter_factory(context)
    eligibility = adapter.validate_eligibility(frame, context)
    if not eligibility.eligible:
        # The champion was eligible on the backtest's training window and is not
        # on the full history: an honest, and reportable, state.
        result["unavailable_reason"] = (
            f"The champion {selection.champion_model_id!r} is not eligible on "
            f"this scope's full history: {eligibility.reason}"
        )
        result["model_id"] = selection.champion_model_id
        return result

    future = _future_frame(frame, horizons=horizons, exog_columns=exog_columns)
    try:
        adapter.fit(frame, context)
        raw = adapter.predict(future, context)
    except Exception as exc:  # noqa: BLE001 - one scope's failure is not the run's
        result["unavailable_reason"] = (
            f"The champion {selection.champion_model_id!r} refit on the full "
            f"history and failed: {type(exc).__name__}: {exc}"[:500]
        )
        result["model_id"] = selection.champion_model_id
        return result

    values = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
    if values.size != len(horizons):
        result["unavailable_reason"] = (
            f"The champion returned {values.size} predictions for "
            f"{len(horizons)} horizons."
        )
        result["model_id"] = selection.champion_model_id
        return result

    bound = forecast_magnitude_bound(frame[TARGET_COL])
    largest = float(np.nanmax(np.abs(values))) if values.size else 0.0
    if not np.all(np.isfinite(values)) or largest > bound:
        result["unavailable_reason"] = (
            f"The forecast diverged: largest magnitude {largest:.3g} against a "
            f"bound of {bound:.3g}. It is refused rather than published, for the "
            "same reason a divergent backtest is not scored."
        )
        result["model_id"] = selection.champion_model_id
        return result

    values = np.clip(values, 0.0, None)
    result["point"] = values
    result["model_id"] = selection.champion_model_id
    result["model_display_name"] = selection.champion_display_name
    result["model_run_id"] = selection.champion_model_run_id
    result["champion_selection_id"] = selection.id
    result["forecast_source"] = (
        "champion" if kind in {"overall", "region", "branch"} else "segment_champion"
    )
    result["target_source"] = _dominant_target_source(frame)
    result["is_censored"] = bool(frame[CENSORED_COL].fillna(False).astype(bool).any())
    result["drivers"] = {
        # The whole resolution, including which candidate periods were
        # rejected and why - the Forecast Explorer shows it as the driver, and
        # "no seasonality was used" is more useful with the reason attached.
        "seasonality": seasonal.as_dict(),
        "seasonal_period": seasonal.period,
        "exog_columns": list(exog_columns),
        "history_months": int(len(frame)),
        "segment": sparsity.segment.value,
        "adi": sparsity.adi,
        "cv_squared": sparsity.cv_squared,
        "parameters": adapter.parameter_metadata(),
        "features": adapter.feature_metadata(),
    }

    quantiles, provenance = _quantiles_for(
        values,
        model_id=selection.champion_model_id,
        scope_level=scope.scope_level,
        segment=sparsity.segment.value,
        horizons=horizons,
        calibrations=calibrations,
        scope_residuals=_scope_residuals(selection.champion_model_run_id),
    )
    result["quantiles"] = quantiles
    result["quantile_provenance"] = provenance
    return result


def _dominant_target_source(frame: pd.DataFrame) -> str | None:
    if "target_source" not in frame.columns:
        return None
    counts = frame["target_source"].dropna().value_counts()
    return str(counts.index[0]) if len(counts) else None


def _future_frame(
    history: pd.DataFrame,
    *,
    horizons: Sequence[int],
    exog_columns: Sequence[str],
) -> pd.DataFrame:
    """The rows the adapters predict against.

    The target column is present and null: it is the thing being forecast, and
    an adapter that silently read an actual out of it would be leaking. The
    calendar exogenous columns are re-derived from the future period index,
    which is exactly why the exogenous set is restricted to calendar features -
    they are the ones genuinely knowable for a month that has not happened.
    """
    last = int(history[PERIOD_COL].max())
    rows = pd.DataFrame({PERIOD_COL: [last + int(h) for h in horizons]})
    rows[TARGET_COL] = np.nan
    if CENSORED_COL in history.columns:
        rows[CENSORED_COL] = False

    # Static attributes are constant per series, so the last observed value is
    # also the future value. Copied rather than re-derived so a model that
    # encodes them sees the same categories it was fitted on.
    static = [
        column
        for column in history.columns
        if column not in {PERIOD_COL, TARGET_COL, CENSORED_COL}
        and history[column].nunique(dropna=True) <= 1
    ]
    for column in static:
        series = history[column].dropna()
        rows[column] = series.iloc[-1] if len(series) else np.nan

    prepared, _ = prepare_local_series_frame(rows, period_col=PERIOD_COL)
    for column in exog_columns:
        if column not in prepared.columns:
            prepared[column] = np.nan
    return prepared



# ----------------------------------------------------------------------
# Interval calibration
# ----------------------------------------------------------------------

#: Why a scope's own residuals are preferred over the run's pooled cells.
#:
#: The training run pools residuals by (model, horizon, demand segment) across
#: **every scope it evaluated** (`docs/DECISIONS.md` D-010), and the offsets are
#: absolute quantities. At the aggregate tier those scopes differ in magnitude
#: by more than fifty times - a small product-group segment against the national
#: total - so an absolute offset drawn from the mixed pool is meaningless at
#: either end of it. Measured on the real run: the national q95 came out 3.2%
#: above the point forecast while that same model's national WAPE was 4.58%, an
#: interval narrower than the model's own average error.
#:
#: So a scope is calibrated from **its own** out-of-sample residuals, which are
#: on its own scale, and the run's pooled cell is the fallback for a scope with
#: too few of them. Both paths report their residual count and pooling level, so
#: a thin calibration is visible rather than implied to be solid.
SCOPE_POOLING_LEVELS: tuple[str, ...] = ("scope_horizon", "scope_all_horizons")


def _scope_residuals(model_run_id: str | None) -> dict[int, list[float]]:
    """This scope's champion's out-of-sample residuals, keyed by horizon.

    `(actual - prediction) / prediction`, matching `ResidualStore`: a positive
    residual means the model under-forecast, and the upper tail is the one that
    matters for stock cover. Relative rather than absolute so the value is on
    the same footing as the run's pooled cells (D-089).
    """
    if not model_run_id:
        return {}
    by_horizon: dict[int, list[float]] = {}
    with session_scope() as db:
        row = db.get(ModelRun, model_run_id)
        if row is None:
            return {}
        for origin in row.origins_json or []:
            actuals = origin.get("actuals") or []
            predictions = origin.get("predictions") or []
            horizons = origin.get("horizons") or []
            for index in range(min(len(actuals), len(predictions))):
                horizon = int(horizons[index]) if index < len(horizons) else index + 1
                prediction = float(predictions[index])
                if prediction <= 0.0:
                    continue
                # Relative, matching `ResidualStore` - see D-089.
                by_horizon.setdefault(horizon, []).append(
                    (float(actuals[index]) - prediction) / prediction
                )
    return by_horizon


def _offset_from(
    residuals: Sequence[float], level: float, pooling_level: str
) -> QuantileOffset | None:
    """One offset from one residual pool, labelled with how it was obtained.

    `conformal` when the required order statistic falls inside the sample,
    `empirical` when it has to be interpolated - the same distinction, and the
    same thresholds, the pooled store uses.
    """
    values = np.sort(np.asarray([r for r in residuals if np.isfinite(r)], dtype=float))
    count = int(values.size)
    if count < MIN_RESIDUALS:
        return None
    needed = conformal_minimum(level)
    if count >= needed:
        rank = int(np.ceil((count + 1) * level)) - 1
        return QuantileOffset(
            level=level,
            offset=float(values[min(rank, count - 1)]),
            method="conformal",
            residual_count=count,
            pooling_level=pooling_level,
        )
    return QuantileOffset(
        level=level,
        offset=float(np.quantile(values, level)),
        method="empirical",
        residual_count=count,
        pooling_level=pooling_level,
        note=(
            f"{count} residuals is above the {MIN_RESIDUALS}-residual floor but "
            f"below the {needed} a q{int(level * 100)} order statistic needs, so "
            "this offset interpolates the tail rather than measuring it"
        ),
    )


def _scope_calibration(
    *,
    model_id: str,
    segment: str,
    horizon: int,
    by_horizon: dict[int, list[float]],
) -> Calibration | None:
    """A calibration built from one scope's own residuals, or `None`.

    Each level falls back independently along `SCOPE_POOLING_LEVELS`, because
    q80 can be honest on a pool where q95 is not.
    """
    pools: list[tuple[str, list[float]]] = [
        ("scope_horizon", list(by_horizon.get(horizon, ()))),
        (
            "scope_all_horizons",
            [value for values in by_horizon.values() for value in values],
        ),
    ]
    calibration = Calibration(model_id=model_id, horizon=horizon, segment=segment)
    for key in QUANTILE_KEYS:
        level = float(key[1:]) / 100.0
        # A scope has at most twelve residuals of its own (two origins x six
        # horizons). q95 needs nineteen to put the order statistic inside the
        # sample, so below that the scope pool can only extrapolate its own
        # tail - measured at 72.9% coverage for a band claiming 95%, and the
        # oracle calibrated on the scored months could not beat 83.5% from the
        # same twelve points (D-089).
        #
        # Since residuals became relative they are scale-free, so the run's
        # pooled cell is a legitimate source rather than a mixture of
        # magnitudes. Levels the scope cannot support are therefore left unset
        # and filled from that larger pool by the caller.
        need = conformal_minimum(level)
        for pooling_level, residuals in pools:
            if len(residuals) < need:
                continue
            offset = _offset_from(residuals, level, pooling_level)
            if offset is not None:
                calibration.offsets[key] = offset
                break
    return calibration if calibration.offsets else None


def _quantiles_for(
    point: np.ndarray,
    *,
    model_id: str,
    segment: str,
    horizons: Sequence[int],
    calibrations: dict[tuple[str, int, str], QuantileCalibration],
    scope_residuals: dict[int, list[float]] | None = None,
    scope_level: str = "series",
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    """Per-horizon quantiles, from this scope's own residuals where possible.

    Each horizon is calibrated separately, because a six-month-ahead error
    distribution is wider than a one-month-ahead one; pooling them would
    understate q95 at long horizons and overstate it at short ones.

    The scope's own residuals are preferred over the run's pooled cells - see
    `SCOPE_POOLING_LEVELS` for the measured reason - and the pooled cell is the
    fallback when the scope has fewer than `MIN_RESIDUALS` of its own.
    """
    output = {key: np.full(len(horizons), np.nan) for key in QUANTILE_KEYS}
    provenance: list[dict[str, Any]] = []
    by_horizon = scope_residuals or {}

    for index, horizon in enumerate(horizons):
        local = _scope_calibration(
            model_id=model_id,
            segment=segment,
            horizon=int(horizon),
            by_horizon=by_horizon,
        )
        # The run's pooled cell mixes every scope that shares a model, horizon
        # and demand segment - and a branch x SKU cell has a far larger
        # *relative* error than a national total even when both are "smooth".
        # Pooling across levels widened the national q95 to 93-162% above the
        # point forecast, which is not an interval anybody can plan against.
        #
        # The 91.1% coverage measured for the pooled cell was measured on
        # series scopes, so that is where it is used. An aggregate keeps its
        # own residuals: its relative error is small and stable, and twelve of
        # them beat a pool drawn from a different population (D-089).
        cell = None
        if scope_level == "series":
            cell = calibrations.get(
                (model_id, int(horizon), segment)
            ) or calibrations.get((model_id, int(horizon), "all"))

        if local is not None and (cell is None or len(local.offsets) == len(QUANTILE_KEYS)):
            values, _report = apply_calibration([float(point[index])], local)
            for key in QUANTILE_KEYS:
                series = values.get(key) or [None]
                if series and series[0] is not None:
                    output[key][index] = float(series[0])
            deepest = local.offsets.get("q95") or next(iter(local.offsets.values()))
            provenance.append(
                {
                    "horizon": int(horizon),
                    "available": True,
                    "method": deepest.method,
                    "pooling_level": deepest.pooling_level,
                    "residual_count": deepest.residual_count,
                    "segment": segment,
                    "source": "scope_residuals",
                    "note": deepest.note,
                }
            )
            continue

        if cell is None:
            provenance.append(
                {
                    "horizon": int(horizon),
                    "available": False,
                    "reason": (
                        f"No calibration cell for ({model_id}, h{horizon}, "
                        f"{segment}), so no interval is published for this "
                        "horizon. A guessed interval is worse than none."
                    ),
                }
            )
            continue

        offsets = cell.offsets_json or {}
        # Built from the run's pooled cell, then overridden level by level by
        # anything the scope could support on its own - its own residuals are
        # the better estimate where there are enough of them.
        calibration = Calibration(
            model_id=model_id,
            horizon=int(horizon),
            segment=segment,
            offsets={
                key: QuantileOffset(
                    level=float(key[1:]) / 100.0,
                    offset=(offsets.get(key) or {}).get("offset"),
                    method=str((offsets.get(key) or {}).get("method") or "unknown"),
                    residual_count=int(
                        (offsets.get(key) or {}).get("residual_count") or 0
                    ),
                    pooling_level=str(
                        (offsets.get(key) or {}).get("pooling_level") or "unknown"
                    ),
                    note=(offsets.get(key) or {}).get("note"),
                )
                for key in QUANTILE_KEYS
                if key in offsets
            },
        )
        # The scope's own residuals are the better estimate wherever it had
        # enough of them; the pooled cell covers only the levels it could not
        # support. Merging per level rather than choosing one source wholesale
        # means q80 can be local while q95 comes from the larger pool.
        local_levels: list[str] = []
        if local is not None:
            for key, offset in local.offsets.items():
                calibration.offsets[key] = offset
                local_levels.append(key)

        if not calibration.offsets:
            provenance.append(
                {"horizon": int(horizon), "available": False, "reason": "empty cell"}
            )
            continue

        values, _report = apply_calibration([float(point[index])], calibration)
        for key in QUANTILE_KEYS:
            series = values.get(key) or [None]
            if series and series[0] is not None:
                output[key][index] = float(series[0])
        provenance.append(
            {
                "horizon": int(horizon),
                "available": True,
                "method": cell.method,
                "pooling_level": cell.pooling_level,
                "residual_count": cell.residual_count,
                "segment": cell.segment,
                "source": "run_pooled_cell",
                "note": (
                    "This scope had fewer than "
                    f"{MIN_RESIDUALS} residuals of its own, so the run's pooled "
                    "cell was used. Pooled offsets are absolute and drawn from "
                    "scopes of mixed magnitude, so this interval's width may not "
                    "match this scope's scale."
                ),
            }
        )

    return output, provenance


def _provenance_summary(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    levels: dict[str, int] = {}
    methods: dict[str, int] = {}
    sources: dict[str, int] = {}
    missing = 0
    for result in results:
        for entry in result.get("quantile_provenance") or []:
            if not entry.get("available"):
                missing += 1
                continue
            level = str(entry.get("pooling_level"))
            method = str(entry.get("method"))
            source = str(entry.get("source") or "unknown")
            levels[level] = levels.get(level, 0) + 1
            methods[method] = methods.get(method, 0) + 1
            sources[source] = sources.get(source, 0) + 1
    return {
        "pooling_levels": levels,
        "methods": methods,
        "sources": sources,
        "horizons_without_interval": missing,
    }


# ----------------------------------------------------------------------
# Reconciliation
# ----------------------------------------------------------------------


def _future_periods(origin_period: str, horizons: Sequence[int]) -> list[str]:
    """The calendar months the horizons land on, from a `YYYY-MM` origin."""
    if not origin_period or "-" not in origin_period:
        return [f"h{h}" for h in horizons]
    year, month = (int(part) for part in origin_period.split("-")[:2])
    output: list[str] = []
    for horizon in horizons:
        total = (year * 12 + (month - 1)) + int(horizon)
        output.append(f"{total // 12:04d}-{total % 12 + 1:02d}")
    return output


def _resolve_base_level(
    by_level: dict[str, list[dict[str, Any]]], panel: pd.DataFrame
) -> tuple[str | None, list[str]]:
    """The finest level that is a **complete** decomposition of its parents.

    The local tier forecasts the top-N series by value, not the whole network,
    so a series level with 100 scopes against a 68,675-series panel cannot be
    reconciled into its branches: the projection would either invent the
    missing series or overwrite the branch aggregate with a subtotal of the
    sampled part. Measured consequence of getting this wrong: branch and region
    totals disagreed by 37,794 units while the run still reported
    `coherent: true`, because the projection had been coherent over the subset
    it was given.

    Returns the base level and the levels below it that were skipped.
    """
    partial: list[str] = []
    for level in LEVEL_ORDER:
        scopes = by_level.get(level)
        if not scopes:
            continue
        if level == "series":
            total_series = (
                int(panel[SERIES_COL].nunique()) if SERIES_COL in panel.columns else 0
            )
            if total_series and len(scopes) < total_series:
                partial.append(level)
                continue
        return level, partial
    return None, partial


#: What a rolled-up row says in place of a model name. It is not a model, and
#: the model_id stays `None` so nothing can mistake it for one - but a blank
#: cell on screen reads as a bug rather than as a statement, so the row says
#: plainly where its number came from.
ROLLED_UP_DISPLAY = "Added up from the SKUs beneath it"
ROLLED_UP_SOURCE = "sum_of_children"


def _mark_rolled_up(
    result: dict[str, Any], values: "np.ndarray", *, members: str, member_count: int
) -> None:
    """Publish an aggregate that was computed by addition, and say so."""
    result["point"] = values
    result["model_id"] = None
    result["model_display_name"] = ROLLED_UP_DISPLAY
    result["forecast_source"] = ROLLED_UP_SOURCE
    result["unavailable_reason"] = None
    result["drivers"] = {
        "method": "sum of children",
        "members_level": members,
        "member_count": member_count,
        "note": (
            "No model was trained for this scope, so its figure is the total of "
            f"the {member_count} {members} forecast(s) underneath it. It agrees "
            "with its parts by construction. It carries no prediction interval "
            "of its own: adding up each SKU's upper bound would assume every "
            "SKU misses high in the same month, which is not what the residuals "
            "show."
        ),
    }


def _publish_rolled_up(
    rolled: dict[tuple[str, str], "np.ndarray"],
    aggregate_results: dict[tuple[str, str], dict[str, Any]],
    *,
    base_level: str | None,
    horizons: Sequence[int],
) -> list[str]:
    """Turn every implied node value into a published row. Returns their keys."""
    published: list[str] = []
    for scope, values in rolled.items():
        result = aggregate_results.get(scope)
        if result is None or not np.all(np.isfinite(values)):
            continue
        _mark_rolled_up(
            result,
            np.clip(values, 0.0, None),
            members=str(base_level or "child"),
            member_count=int(result.get("member_series") or 0),
        )
        published.append(f"{scope[0]}/{scope[1]}")
    return published


def _roll_up_segments(
    results: list[dict[str, Any]], *, panel: pd.DataFrame, horizons: Sequence[int]
) -> list[str]:
    """The same addition for value-class and product-group scopes.

    Those sit outside the branch/region/national hierarchy, so reconciliation
    never reaches them. They are still a plain sum of the series that belong to
    them, and the panel says which those are.
    """
    series_points = {
        result["scope_key"]: result["point"]
        for result in results
        if result["scope_level"] == "series" and result.get("point") is not None
    }
    if not series_points:
        return []

    published: list[str] = []
    for result in results:
        if result["scope_level"] != "segment" or result.get("point") is not None:
            continue
        column, _, value = str(result["scope_key"]).partition("=")
        if column not in SEGMENT_COLUMNS or column not in panel.columns:
            continue
        members = (
            panel.loc[panel[column].astype(str) == value, SERIES_COL]
            .astype(str)
            .unique()
        )
        contributing = [series_points[key] for key in members if key in series_points]
        if not contributing:
            # Genuinely nothing underneath that was forecast. The row keeps the
            # reason it already had rather than gaining a zero.
            continue
        _mark_rolled_up(
            result,
            np.clip(np.sum(contributing, axis=0), 0.0, None),
            members="series",
            member_count=len(contributing),
        )
        published.append(f"segment/{result['scope_key']}")
    return published


def _reconcile_results(
    results: list[dict[str, Any]],
    *,
    panel: pd.DataFrame,
    method: str,
    horizons: Sequence[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reconcile branch -> region -> national, per horizon.

    The base level here is **branch**, not branch x SKU: this run forecasts the
    aggregate tier, and reconciling a level that was not forecast would mean
    inventing its detail. When the series tier is present the same call
    reconciles from there instead.
    """
    by_level: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        by_level.setdefault(result["scope_level"], []).append(result)

    base_level, partial_levels = _resolve_base_level(by_level, panel)
    meta: dict[str, Any] = {
        "method": "none",
        "coherent": False,
        "notes": [],
        "base_level": base_level,
        "partial_levels": partial_levels,
    }
    # A level finer than the base is a deliberate subset - the local tier
    # forecasts the top-N series, not all 68,675 - so its rows are left
    # unreconciled and say so. Reconciling a partial level into its parents
    # would either invent the missing series or silently replace a
    # full-network aggregate with a subtotal of the sampled part.
    for level in partial_levels:
        for result in by_level.get(level, []):
            result["reconciliation_method"] = "none"
            result["reconciliation_note"] = (
                f"This {level} forecast was not reconciled: the {level} tier "
                f"covers {len(by_level.get(level, []))} scope(s), which is a "
                "subset of the network rather than a complete decomposition of "
                f"its parents. Reconciliation ran at the {base_level} level and "
                "above."
            )
    if partial_levels:
        meta["notes"].append(
            f"Level(s) {', '.join(partial_levels)} are a subset of the network, "
            f"so reconciliation ran from {base_level} upward. Their totals are "
            "not expected to equal their parents'."
        )
    if base_level is None or base_level == "national":
        meta["notes"].append(
            "Only one level was forecast, so there is nothing to reconcile."
        )
        for result in results:
            result["reconciliation_method"] = "none"
        return results, meta

    usable = [r for r in by_level[base_level] if r.get("point") is not None]
    if not usable:
        meta["notes"].append(
            f"No {base_level}-level forecast succeeded, so reconciliation was "
            "skipped and every level is reported as its own model produced it."
        )
        for result in results:
            result["reconciliation_method"] = "none"
        return results, meta

    parents = _parent_map(panel, base_level, [r["scope_key"] for r in usable])
    hierarchy = build_hierarchy(
        [r["scope_key"] for r in usable],
        parents=parents,
        levels=("region", "national") if base_level == "branch" else ("branch", "region", "national"),
    )

    node_lookup = {
        (level if level != "series" else base_level, key): index
        for index, (level, key) in enumerate(hierarchy.nodes)
    }
    # The base level must be in here, not only the levels above it. When the
    # base is `series` it was previously left out, so every base entry of the
    # projection vector stayed zero: reconciliation ran over an all-zero base,
    # reported itself trivially coherent, and the bottom-up sum it hands to a
    # parent with no forecast of its own came out as 0. That is why a branch
    # total read zero against 2,410 units of SKUs beneath it.
    levels_in_play = {"branch", "region", "national"}
    if base_level:
        levels_in_play.add(base_level)
    aggregate_results = {
        (r["scope_level"], r["scope_key"]): r
        for r in results
        if r["scope_level"] in levels_in_play
    }

    crossings = 0
    negatives = 0
    coherent = True
    worst = 0.0
    #: Aggregate scopes filled by adding up their children, keyed by scope.
    rolled: dict[tuple[str, str], np.ndarray] = {}
    chosen_method = method
    fallback_from: str | None = None
    fallback_reason: str | None = None
    intensity: float | None = None
    notes: list[str] = []

    for position, _horizon in enumerate(horizons):
        vector = np.zeros(hierarchy.node_count)
        for (level, key), index in node_lookup.items():
            result = aggregate_results.get((level, key))
            if result is None or result.get("point") is None:
                continue
            vector[index] = float(result["point"][position])
        # A node with no forecast of its own takes its children's sum, which is
        # what bottom-up would give it, rather than entering the projection as
        # a zero and dragging its parents down.
        #
        # That sum used to be used for the projection and then dropped, so a
        # branch with no champion of its own was computed and then written as a
        # blank row. It is a real answer - the branch total *is* the sum of its
        # SKUs - so it is kept here and published, labelled as an addition
        # rather than as a model output.
        implied = hierarchy.S @ vector[: hierarchy.base_count]
        for (level, key), index in node_lookup.items():
            if index < hierarchy.base_count:
                continue
            result = aggregate_results.get((level, key))
            if result is None or result.get("point") is None:
                vector[index] = implied[index]
                if result is not None:
                    rolled.setdefault(
                        (level, key), np.full(len(horizons), np.nan)
                    )[position] = implied[index]

        residuals = _residual_matrix(hierarchy, node_lookup, aggregate_results)
        outcome = reconcile(
            hierarchy, vector, method=method, residuals=residuals
        )
        chosen_method = outcome.method
        fallback_from = outcome.fallback_from or fallback_from
        fallback_reason = outcome.fallback_reason or fallback_reason
        intensity = outcome.shrinkage_intensity if outcome.shrinkage_intensity is not None else intensity
        negatives += outcome.negatives_clipped
        coherent = coherent and outcome.coherent
        worst = max(worst, outcome.max_incoherence)
        for note in outcome.notes:
            if note not in notes:
                notes.append(note)

        quantile_input = {
            key: np.array(
                [
                    _quantile_at(aggregate_results, node_lookup, key, position, index, outcome)
                    for index in range(hierarchy.node_count)
                ]
            )
            for key in QUANTILE_KEYS
        }
        adjusted, report = reconcile_quantiles(
            hierarchy, outcome.values, quantile_input
        )
        crossings += int(report["crossings_corrected"])

        for (level, key), index in node_lookup.items():
            result = aggregate_results.get((level, key))
            if result is None:
                continue
            result.setdefault("reconciled_point", np.full(len(horizons), np.nan))
            result.setdefault(
                "reconciled_quantiles",
                {q: np.full(len(horizons), np.nan) for q in QUANTILE_KEYS},
            )
            result["reconciled_point"][position] = outcome.values[index]
            result["reconciliation_method"] = outcome.method
            for q in QUANTILE_KEYS:
                value = adjusted.get(q)
                if value is not None:
                    result["reconciled_quantiles"][q][position] = value[index]

    rolled_up = _publish_rolled_up(
        rolled, aggregate_results, base_level=base_level, horizons=horizons
    )
    rolled_up.extend(_roll_up_segments(results, panel=panel, horizons=horizons))
    if rolled_up:
        meta["notes"].append(
            f"{len(rolled_up)} scope(s) had no champion of their own and were "
            f"filled by adding up the {base_level} forecasts beneath them: "
            f"{', '.join(sorted(rolled_up)[:8])}"
            + (" and others" if len(rolled_up) > 8 else "")
            + ". Those rows are totals, not model output, and carry no "
            "prediction interval of their own."
        )
    meta["rolled_up"] = rolled_up

    meta.update(
        {
            "method": chosen_method,
            "requested": method,
            "fallback_from": fallback_from,
            "fallback_reason": fallback_reason,
            "shrinkage_intensity": intensity,
            "coherent": coherent,
            "max_incoherence": worst,
            "negatives_clipped": negatives,
            "quantile_crossings_corrected": crossings,
            "notes": notes,
            "nodes": hierarchy.node_count,
            "base_level": base_level,
        }
    )
    return results, meta


def _quantile_at(
    aggregate_results: dict[tuple[str, str], dict[str, Any]],
    node_lookup: dict[tuple[str, str], int],
    key: str,
    position: int,
    index: int,
    outcome: Any,
) -> float:
    """A node's raw quantile before reconciliation, or its point forecast.

    Falling back to the point forecast (rather than to zero or NaN) keeps the
    ordering valid for a node whose interval could not be calibrated: the band
    collapses onto the point, which is honest about carrying no width.
    """
    for scope, position_index in node_lookup.items():
        if position_index != index:
            continue
        result = aggregate_results.get(scope)
        if result is None:
            break
        values = (result.get("quantiles") or {}).get(key)
        if values is not None and position < len(values):
            value = float(values[position])
            if np.isfinite(value):
                return value
        point = result.get("point")
        if point is not None and position < len(point):
            return float(point[position])
        break
    return float(outcome.values[index])


def _parent_map(
    panel: pd.DataFrame, base_level: str, keys: Sequence[str]
) -> list[dict[str, str]]:
    """Each base key's parents, read from the panel rather than parsed."""
    if base_level == "branch":
        pairs = (
            panel[["canonical_branch", "region"]]
            .dropna(subset=["canonical_branch"])
            .drop_duplicates("canonical_branch")
            .set_index("canonical_branch")["region"]
            .to_dict()
        )
        return [{"region": str(pairs.get(key) or "UNKNOWN")} for key in keys]
    if base_level == "series":
        frame = (
            panel[[SERIES_COL, "canonical_branch", "region"]]
            .dropna(subset=[SERIES_COL])
            .drop_duplicates(SERIES_COL)
            .set_index(SERIES_COL)
        )
        return [
            {
                "branch": str(frame["canonical_branch"].get(key) or "UNKNOWN"),
                "region": str(frame["region"].get(key) or "UNKNOWN"),
            }
            for key in keys
        ]
    return [{} for _key in keys]


def _residual_matrix(
    hierarchy: Hierarchy,
    node_lookup: dict[tuple[str, str], int],
    aggregate_results: dict[tuple[str, str], dict[str, Any]],
) -> np.ndarray | None:
    """Node-level out-of-sample residuals, for the MinT weight matrix.

    Read from each scope's champion `model_run` rather than recomputed, so the
    covariance comes from the same folds the champion was chosen on. Returns
    `None` when too few nodes have residuals, which makes `reconcile` fall back
    and say so.
    """
    with session_scope() as db:
        columns: dict[int, list[float]] = {}
        length = 0
        for scope, index in node_lookup.items():
            result = aggregate_results.get(scope)
            if result is None or not result.get("model_run_id"):
                continue
            row = db.get(ModelRun, result["model_run_id"])
            if row is None:
                continue
            residuals: list[float] = []
            for origin in row.origins_json or []:
                actuals = origin.get("actuals") or []
                predictions = origin.get("predictions") or []
                residuals.extend(
                    float(p) - float(a)
                    for a, p in zip(actuals, predictions)
                    if a is not None and p is not None
                )
            if residuals:
                columns[index] = residuals
                length = max(length, len(residuals))

    if len(columns) < 2 or length < 2:
        return None
    matrix = np.zeros((length, hierarchy.node_count))
    for index, values in columns.items():
        padded = list(values) + [0.0] * (length - len(values))
        matrix[:, index] = padded[:length]
    return matrix


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------


def _persist(
    run_id: str, results: Sequence[dict[str, Any]], origin_period: str
) -> tuple[int, int]:
    """One row per (scope, period), including the unavailable ones."""
    written = 0
    unavailable = 0
    with session_scope() as db:
        for result in results:
            periods = result["periods"]
            horizons = result["horizons"]
            point = result.get("reconciled_point")
            raw_point = result.get("point")
            quantiles = result.get("reconciled_quantiles") or result.get("quantiles") or {}
            provenance = {
                entry.get("horizon"): entry
                for entry in (result.get("quantile_provenance") or [])
            }

            for index, (period, horizon) in enumerate(zip(periods, horizons)):
                if raw_point is None:
                    db.add(
                        ForecastRow(
                            forecast_run_id=run_id,
                            scope_level=result["scope_level"],
                            scope_key=result["scope_key"],
                            period=period,
                            horizon=int(horizon),
                            model_id=result.get("model_id"),
                            demand_segment=result.get("segment"),
                            unavailable_reason=result["unavailable_reason"],
                        )
                    )
                    unavailable += 1
                    continue

                base_value = float(raw_point[index])
                final = (
                    float(point[index])
                    if point is not None and np.isfinite(point[index])
                    else base_value
                )
                cell = provenance.get(int(horizon)) or {}
                db.add(
                    ForecastRow(
                        forecast_run_id=run_id,
                        scope_level=result["scope_level"],
                        scope_key=result["scope_key"],
                        canonical_branch=result.get("canonical_branch"),
                        canonical_sku=result.get("canonical_sku"),
                        region=result.get("region"),
                        demand_segment=result.get("segment"),
                        period=period,
                        horizon=int(horizon),
                        model_id=result.get("model_id"),
                        model_display_name=result.get("model_display_name"),
                        model_run_id=result.get("model_run_id"),
                        champion_selection_id=result.get("champion_selection_id"),
                        forecast_source=result.get("forecast_source"),
                        point_forecast=final,
                        q80=_finite(quantiles.get("q80"), index),
                        q90=_finite(quantiles.get("q90"), index),
                        q95=_finite(quantiles.get("q95"), index),
                        base_forecast=base_value,
                        reconciliation_adjustment=final - base_value,
                        reconciliation_method=result.get("reconciliation_method"),
                        quantile_method=cell.get("method"),
                        quantile_pooling_level=cell.get("pooling_level"),
                        quantile_residual_count=int(cell.get("residual_count") or 0),
                        target_source=result.get("target_source"),
                        is_censored=result.get("is_censored"),
                        unavailable_reason=(
                            None
                            if cell.get("available", True)
                            else cell.get("reason")
                        ),
                        drivers_json=result.get("drivers"),
                    )
                )
                written += 1
    return written, unavailable


def _finite(values: Any, index: int) -> float | None:
    if values is None:
        return None
    try:
        value = float(values[index])
    except (IndexError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


# ----------------------------------------------------------------------
# Reading forecasts
# ----------------------------------------------------------------------


def query_rows(
    db: Session,
    *,
    forecast_run_id: str,
    scope_level: str | None = None,
    scope_key: str | None = None,
    period_from: str | None = None,
    period_to: str | None = None,
    model_id: str | None = None,
    include_unavailable: bool = True,
    offset: int = 0,
    limit: int = 200,
) -> tuple[list[ForecastRow], int]:
    conditions = [ForecastRow.forecast_run_id == forecast_run_id]
    if scope_level:
        conditions.append(ForecastRow.scope_level == scope_level)
    if scope_key:
        conditions.append(ForecastRow.scope_key == scope_key)
    if period_from:
        conditions.append(ForecastRow.period >= period_from)
    if period_to:
        conditions.append(ForecastRow.period <= period_to)
    if model_id:
        conditions.append(ForecastRow.model_id == model_id)
    if not include_unavailable:
        conditions.append(ForecastRow.point_forecast.is_not(None))

    total = (
        db.scalar(select(func.count()).select_from(ForecastRow).where(*conditions)) or 0
    )
    rows = list(
        db.scalars(
            select(ForecastRow)
            .where(*conditions)
            .order_by(
                ForecastRow.scope_level,
                ForecastRow.scope_key,
                ForecastRow.period,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, int(total)


def series_payload(
    db: Session,
    *,
    forecast_run_id: str,
    scope_level: str,
    scope_key: str,
    history_months: int = 24,
) -> dict[str, Any]:
    """One scope: its history, its six horizons, and the metrics behind them."""
    run = get_run(db, forecast_run_id)
    rows, _total = query_rows(
        db,
        forecast_run_id=forecast_run_id,
        scope_level=scope_level,
        scope_key=scope_key,
        limit=1000,
    )
    if not rows:
        raise NotFoundError(
            f"Forecast run {forecast_run_id!r} has no rows for "
            f"{scope_level}/{scope_key}."
        )

    history, history_note = _history_for(
        run.panel_build_id, scope_level, scope_key, history_months
    )
    champion = rows[0]
    metrics: dict[str, Any] | None = None
    if champion.model_run_id:
        model_run = db.get(ModelRun, champion.model_run_id)
        if model_run is not None:
            metrics = {
                "model_id": model_run.model_id,
                "display_name": model_run.display_name,
                "wape": model_run.wape,
                "mae": model_run.mae,
                "rmse": model_run.rmse,
                "mape": model_run.mape,
                "smape": model_run.smape,
                "mase": model_run.mase,
                "bias": model_run.bias,
                "validation_points": model_run.validation_points,
                "evaluation_mode": model_run.evaluation_mode,
            }

    return {
        "forecast_run_id": forecast_run_id,
        "training_run_id": run.training_run_id,
        "scope_level": scope_level,
        "scope_key": scope_key,
        "origin_period": run.origin_period,
        "history": history,
        "history_unavailable_reason": history_note,
        "forecasts": rows,
        "validation_metrics": metrics,
        "drivers": champion.drivers_json,
        "reconciliation_method": run.reconciliation_method,
        "coherent": run.coherent,
        "snapshot_caveat": (
            "Forecasts are generated from the panel's own history and carry the "
            "target-source mix of the window they were fitted on; a "
            "`sales_proxy` row is a labelled substitute, not ordered demand."
        ),
    }


def _history_for(
    build_id: str, scope_level: str, scope_key: str, months: int
) -> tuple[list[dict[str, Any]], str | None]:
    """Observed history for one scope, summed from the panel.

    Returns the points and, when there are none, why. History is supplementary
    to the forecast rows, which live in the database: an unreadable panel
    artifact must degrade this view rather than fail a request whose primary
    content is already available.
    """
    with session_scope() as db:
        build = db.get(PanelBuild, build_id)
        artifacts = (build.artifacts_json or {}) if build else {}
    path = artifacts.get("panel")
    if not path:
        return [], (
            "The panel build recorded no panel artifact, so no history is "
            "available to plot. The forecasts themselves are unaffected."
        )

    # The workspace restriction, applied to the history exactly as it was
    # applied to the forecast.
    #
    # Without it the chart drew a 53-branch actual line against a 2-branch
    # forecast: national history read 200,686 units for Jul 2026 while the
    # forecast for Aug 2026 was 3,310, so the forecast looked like zero. Two
    # different populations on one axis is worse than either alone
    # (docs/DECISIONS.md D-067).
    workspace = resolve_workspace_for_forecast()

    columns = ["period", TARGET_COL, "target_source", CENSORED_COL]
    filters: list[tuple[str, str, Any]] = []
    if workspace.branches is not None:
        columns.append("canonical_branch")
    if workspace.skus is not None:
        columns.append("canonical_sku")
    if scope_level == "branch":
        columns.append("canonical_branch")
        filters.append(("canonical_branch", "==", scope_key))
    elif scope_level == "region":
        columns.append("region")
        filters.append(("region", "==", scope_key))
    elif scope_level == "series":
        columns.append(SERIES_COL)
        filters.append((SERIES_COL, "==", scope_key))
    elif scope_level == "segment" and "=" in scope_key:
        column, value = scope_key.split("=", 1)
        columns.append(column)
        filters.append((column, "==", value))

    try:
        frame = pd.read_parquet(
            path, columns=list(dict.fromkeys(columns)), filters=filters or None
        )
    except (OSError, ValueError, KeyError) as exc:
        return [], (
            f"The panel artifact could not be read ({type(exc).__name__}), so no "
            "history is available to plot. The forecasts themselves are "
            "unaffected."
        )
    frame = workspace.restrict(frame, "canonical_branch")
    if frame.empty:
        return [], (
            f"The panel holds no rows for {scope_level}/{scope_key}, so there is "
            "no history to plot."
        )
    grouped = (
        frame.groupby("period", observed=True)
        .agg(
            actual=(TARGET_COL, "sum"),
            censored=(CENSORED_COL, "any"),
        )
        .reset_index()
        .sort_values("period")
        .tail(months)
    )
    sources = (
        frame.groupby("period", observed=True)["target_source"]
        .agg(lambda values: "order" if set(values.dropna()) == {"order"} else "mixed")
        .to_dict()
    )
    return (
        [
            {
                "period": str(row["period"]),
                "actual": float(row["actual"]),
                "is_censored": bool(row["censored"]),
                "target_source": sources.get(row["period"]),
            }
            for _index, row in grouped.iterrows()
        ],
        None,
    )


def hierarchy_payload(
    db: Session, *, forecast_run_id: str, period: str | None = None
) -> dict[str, Any]:
    """Every level for one period, with the reconciliation adjustment shown."""
    run = get_run(db, forecast_run_id)
    conditions = [ForecastRow.forecast_run_id == forecast_run_id]
    if period:
        conditions.append(ForecastRow.period == period)
    rows = list(
        db.scalars(
            select(ForecastRow)
            .where(*conditions, ForecastRow.point_forecast.is_not(None))
            .order_by(ForecastRow.period, ForecastRow.scope_level)
        )
    )

    levels: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = levels.setdefault(
            row.scope_level,
            {
                "scope_level": row.scope_level,
                "nodes": 0,
                "point_total": 0.0,
                "base_total": 0.0,
                "adjustment_total": 0.0,
                "q95_total": 0.0,
            },
        )
        bucket["nodes"] += 1
        bucket["point_total"] += float(row.point_forecast or 0.0)
        bucket["base_total"] += float(row.base_forecast or 0.0)
        bucket["adjustment_total"] += float(row.reconciliation_adjustment or 0.0)
        bucket["q95_total"] += float(row.q95 or 0.0)

    ordered = [
        levels[level] for level in ("series", "branch", "region", "national") if level in levels
    ]
    # Coherence, re-checked from the stored rows rather than asserted from the
    # run's own flag: two levels that disagree here mean the persisted rows
    # disagree, whatever the projection reported at the time.
    summary = run.summary_json or {}
    reconciliation = summary.get("reconciliation") or {}
    partial_levels = set(reconciliation.get("partial_levels") or [])
    base_level = reconciliation.get("base_level")

    gaps: list[dict[str, Any]] = []
    for lower, upper in zip(ordered, ordered[1:]):
        difference = upper["point_total"] - lower["point_total"]
        scale = max(abs(upper["point_total"]), 1.0)
        matches = abs(difference) <= 1e-6 * scale + 1e-6
        # A level below the reconciliation base is a subset of the network, so
        # its total is not *expected* to match its parent. Reporting that as
        # incoherent would be a false alarm on every run that includes the
        # local tier; reporting it as coherent would be a lie. So the pair
        # carries `expected_coherent` and a reason.
        partial = lower["scope_level"] in partial_levels
        gaps.append(
            {
                "from_level": lower["scope_level"],
                "to_level": upper["scope_level"],
                "difference": difference,
                "coherent": matches,
                "expected_coherent": not partial,
                "reason": (
                    (
                        f"The {lower['scope_level']} tier holds "
                        f"{lower['nodes']} scope(s) - a subset of the network, "
                        f"not a complete decomposition - so reconciliation ran "
                        f"from {base_level or 'a coarser level'} upward and "
                        "these totals are not expected to agree."
                    )
                    if partial
                    else (
                        None
                        if matches
                        else (
                            "These levels were reconciled together and do not "
                            "agree. That is a defect, not an expected gap."
                        )
                    )
                ),
            }
        )

    return {
        "forecast_run_id": forecast_run_id,
        "origin_period": run.origin_period,
        "period": period,
        "levels": ordered,
        "level_gaps": gaps,
        "reconciliation_base_level": base_level,
        "partial_levels": sorted(partial_levels),
        "reconciliation_method": run.reconciliation_method,
        "reconciliation_fallback_from": run.reconciliation_fallback_from,
        "reconciliation_fallback_reason": run.reconciliation_fallback_reason,
        "coherent": run.coherent,
        "max_incoherence": run.max_incoherence,
        "quantile_crossings_corrected": run.quantile_crossings_corrected,
    }
