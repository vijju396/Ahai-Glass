"""CSV exports of exactly what a page displays.

The contract is narrower than it looks: an export must contain **the same rows
and the same columns the page showed**, including the rows that carry a reason
instead of a number. An export that quietly dropped the unavailable rows would
be a different dataset from the one the planner was looking at, and the
difference would be invisible in the file.

So every export here:

- includes the `unavailable_reason` column, and the rows that have one,
- writes an empty cell for an undefined metric rather than a zero,
- carries its provenance in the filename and in a `# ` comment header, so a
  file found on a shared drive months later can be traced back to the run that
  produced it.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.models.forecasts import ForecastRow, ForecastRun
from app.models.training import ModelRun, TrainingRun
from app.services import champion_service, inventory_service

logger = get_logger(__name__)

#: The exports offered, and which page each mirrors.
EXPORT_KINDS: dict[str, str] = {
    "leaderboard": "Model Leaderboard - every model in one scope, ranked or not",
    "forecasts": "Forecast Explorer - forecast rows with quantiles and lineage",
    "recommendations": "Supply Intelligence - order recommendations with their inputs",
    "model_runs": "Training Center - every (scope, model) row of a training run",
}


def _write(
    header: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    provenance: str,
) -> str:
    buffer = io.StringIO()
    buffer.write(f"# {provenance}\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def export(
    db: Session,
    kind: str,
    *,
    training_run_id: str | None = None,
    forecast_run_id: str | None = None,
    scope_level: str = "national",
    scope_key: str = "NATIONAL",
    service_level: int = 95,
    period: str | None = None,
    limit: int = 5000,
) -> tuple[str, str]:
    """Return `(filename, csv_text)` for one export kind."""
    if kind not in EXPORT_KINDS:
        raise ValidationFailedError(
            f"Unknown export kind {kind!r}.",
            details={"valid": sorted(EXPORT_KINDS)},
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if kind == "leaderboard":
        run = champion_service.resolve_run(db, training_run_id)
        board = champion_service.build_leaderboard(
            db, run.id, scope_level=scope_level, scope_key=scope_key
        )
        header = [
            "rank",
            "legacy_rank",
            "model_id",
            "display_name",
            "is_baseline",
            "status",
            "evaluation_mode",
            "wape_pct",
            "mape_pct",
            "accuracy_pct",
            "mae",
            "rmse",
            "smape",
            "mase",
            "bias",
            "validation_points",
            "origins_completed",
            "origins_total",
            "is_champion",
            "is_challenger",
            "exclusion",
            "failure_reason",
            "unavailable_reason",
        ]
        rows = [
            [
                item.rank,
                item.legacy_rank,
                item.candidate.model_id,
                item.candidate.display_name,
                item.candidate.is_baseline,
                item.candidate.status,
                item.candidate.evaluation_mode,
                item.candidate.wape,
                item.candidate.mape,
                item.candidate.accuracy,
                item.candidate.mae,
                item.candidate.rmse,
                item.candidate.smape,
                item.candidate.mase,
                item.candidate.bias,
                item.candidate.validation_points,
                item.candidate.origins_completed,
                item.candidate.origins_total,
                item.is_champion,
                item.is_challenger,
                item.exclusion,
                item.candidate.failure_reason,
                item.exclusion_reason,
            ]
            for item in board.rows
        ]
        provenance = (
            f"AIS leaderboard export | training_run={run.id} | "
            f"scope={scope_level}/{scope_key} | generated={stamp} | "
            f"ranked={board.ranked_count} unranked={board.excluded_count} | "
            "an empty metric cell means undefined, not zero"
        )
        name = f"ais_leaderboard_{scope_level}_{_slug(scope_key)}_{stamp}.csv"
        return name, _write(header, rows, provenance=provenance)

    if kind == "model_runs":
        run = champion_service.resolve_run(db, training_run_id)
        model_rows = list(
            db.scalars(
                select(ModelRun)
                .where(ModelRun.training_run_id == run.id)
                .order_by(
                    ModelRun.tier,
                    ModelRun.scope_level,
                    ModelRun.scope_key,
                    ModelRun.model_id,
                )
                .limit(limit)
            )
        )
        header = [
            "tier",
            "scope_level",
            "scope_key",
            "segment",
            "model_id",
            "display_name",
            "is_baseline",
            "status",
            "evaluation_mode",
            "wape_pct",
            "mape_pct",
            "mae",
            "rmse",
            "smape",
            "mase",
            "bias",
            "validation_points",
            "total_test_points",
            "duplicate_test_points",
            "origins_completed",
            "origins_total",
            "fit_seconds",
            "predict_seconds",
            "failure_reason",
        ]
        rows = [
            [
                row.tier,
                row.scope_level,
                row.scope_key,
                row.segment,
                row.model_id,
                row.display_name,
                row.is_baseline,
                row.status,
                row.evaluation_mode,
                row.wape,
                row.mape,
                row.mae,
                row.rmse,
                row.smape,
                row.mase,
                row.bias,
                row.validation_points,
                row.total_test_points,
                row.duplicate_test_points,
                row.origins_completed,
                row.origins_total,
                row.fit_seconds,
                row.predict_seconds,
                row.failure_reason,
            ]
            for row in model_rows
        ]
        provenance = (
            f"AIS model-run export | training_run={run.id} | generated={stamp} | "
            f"rows={len(rows)} | every (scope, model) the run asked about, "
            "including ineligible, failed and timed-out rows"
        )
        return f"ais_model_runs_{stamp}.csv", _write(header, rows, provenance=provenance)

    if kind == "forecasts":
        run = _forecast_run(db, forecast_run_id)
        conditions = [ForecastRow.forecast_run_id == run.id]
        if scope_level:
            conditions.append(ForecastRow.scope_level == scope_level)
        if period:
            conditions.append(ForecastRow.period == period)
        forecast_rows = list(
            db.scalars(
                select(ForecastRow)
                .where(*conditions)
                .order_by(ForecastRow.scope_key, ForecastRow.period)
                .limit(limit)
            )
        )
        header = [
            "scope_level",
            "scope_key",
            "canonical_branch",
            "canonical_sku",
            "region",
            "demand_segment",
            "period",
            "horizon",
            "model_id",
            "point_forecast",
            "q80",
            "q90",
            "q95",
            "base_forecast",
            "reconciliation_adjustment",
            "reconciliation_method",
            "quantile_method",
            "quantile_pooling_level",
            "quantile_residual_count",
            "target_source",
            "is_censored",
            "forecast_source",
            "training_run_id",
            "model_run_id",
            "champion_selection_id",
            "unavailable_reason",
        ]
        rows = [
            [
                row.scope_level,
                row.scope_key,
                row.canonical_branch,
                row.canonical_sku,
                row.region,
                row.demand_segment,
                row.period,
                row.horizon,
                row.model_id,
                row.point_forecast,
                row.q80,
                row.q90,
                row.q95,
                row.base_forecast,
                row.reconciliation_adjustment,
                row.reconciliation_method,
                row.quantile_method,
                row.quantile_pooling_level,
                row.quantile_residual_count,
                row.target_source,
                row.is_censored,
                row.forecast_source,
                run.training_run_id,
                row.model_run_id,
                row.champion_selection_id,
                row.unavailable_reason,
            ]
            for row in forecast_rows
        ]
        provenance = (
            f"AIS forecast export | forecast_run={run.id} | "
            f"training_run={run.training_run_id} | origin={run.origin_period} | "
            f"reconciliation={run.reconciliation_method} "
            f"coherent={run.coherent} | generated={stamp} | rows={len(rows)} | "
            "a row with unavailable_reason has no forecast, not a zero"
        )
        return f"ais_forecasts_{stamp}.csv", _write(header, rows, provenance=provenance)

    # recommendations
    run = _forecast_run(db, forecast_run_id)
    payload = inventory_service.recommendations(
        db,
        forecast_run_id=run.id,
        period=period,
        service_level=service_level,
        scope_level="series",
        include_unavailable=True,
        limit=limit,
    )
    header = [
        "scope_key",
        "canonical_branch",
        "canonical_sku",
        "forecast_period",
        "service_level",
        "monthly_point_forecast",
        "monthly_quantile_forecast",
        "review_period_days",
        "lead_time_days",
        "protection_period_days",
        "protection_months",
        "usable_stock_on_hand",
        "confirmed_stock_on_order",
        "backorders",
        "order_up_to_level",
        "raw_recommended_order",
        "recommended_order",
        "days_of_cover",
        "moq",
        "truck_quantity",
        "target_source",
        "is_censored",
        "forecast_model_id",
        "is_current_snapshot_estimate",
        "warnings",
        "unavailable_reason",
    ]
    rows = [
        [
            item["scope_key"],
            item["canonical_branch"],
            item["canonical_sku"],
            item["forecast_period"],
            item["service_level"],
            item["monthly_point_forecast"],
            item["monthly_quantile_forecast"],
            item["review_period_days"],
            item["lead_time_days"],
            item["protection_period_days"],
            item["protection_months"],
            item["usable_stock_on_hand"],
            item["confirmed_stock_on_order"],
            item["backorders"],
            item["order_up_to_level"],
            item["raw_recommended_order"],
            item["recommended_order"],
            item["days_of_cover"],
            item["moq"],
            item["truck_quantity"],
            item["target_source"],
            item["is_censored"],
            item["forecast_model_id"],
            item["is_current_snapshot_estimate"],
            " | ".join(item["warnings"]),
            item["unavailable_reason"],
        ]
        for item in payload["items"]
    ]
    provenance = (
        f"AIS recommendation export | forecast_run={run.id} | "
        f"period={payload['period']} | service_level=q{service_level} | "
        f"generated={stamp} | rows={len(rows)} | CURRENT-SNAPSHOT ESTIMATES: "
        "stock is a single snapshot and there is no open-order history, so "
        "confirmed_stock_on_order and backorders are zero by absence"
    )
    return f"ais_recommendations_q{service_level}_{stamp}.csv", _write(
        header, rows, provenance=provenance
    )


def _forecast_run(db: Session, forecast_run_id: str | None) -> ForecastRun:
    if forecast_run_id:
        run = db.get(ForecastRun, forecast_run_id)
        if run is None:
            raise NotFoundError(f"No forecast run with id {forecast_run_id!r}.")
        return run
    run = db.scalars(
        select(ForecastRun)
        .where(ForecastRun.status == "completed")
        .order_by(ForecastRun.created_at.desc())
        .limit(1)
    ).first()
    if run is None:
        raise NotFoundError(
            "No completed forecast run exists to export.",
            remediation="POST /api/forecasts/runs first.",
        )
    return run


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)[:60]
