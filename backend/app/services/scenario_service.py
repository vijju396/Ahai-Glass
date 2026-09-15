"""Scenario planning: what-if arithmetic over a baseline forecast.

A scenario is a **transformation of a stored forecast**, never a re-forecast and
never a write to the baseline. That is the whole design:

- the baseline forecast run is read-only here, so a scenario can always be
  compared against what was actually produced;
- the adjustment is stored as its inputs (a multiplier, a service level, a lead
  time), not as a set of overwritten numbers, so it can be re-derived and
  audited;
- a scenario says which levers it pulled, and a lever the source data cannot
  support is refused rather than silently ignored.

What a scenario may change:

**Demand multiplier** — scales the point forecast and its quantiles. Applied to
both, because scaling the point alone would leave an interval that no longer
brackets it.

**Service level** — switches which quantile drives the inventory position. This
is not a change to the forecast at all; it is a change to how much of the
forecast distribution is covered.

**Lead time** — changes the protection period. Affects the order quantity
without touching the forecast.

What a scenario may **not** do: invent a forecast for a scope that has none.
A scope with no baseline row stays absent, with its reason.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.domain.ais.inventory import (
    DAYS_PER_MONTH,
    SERVICE_LEVELS,
    InventoryInputs,
    recommend,
)
from app.models.forecasts import ForecastRow, ForecastRun

logger = get_logger(__name__)

#: A multiplier outside this range is almost certainly a mistake rather than a
#: plan, and a scenario that silently accepted 100x would produce an order
#: recommendation nobody could act on.
MULTIPLIER_BOUNDS = (0.1, 5.0)

#: The quantile column each service level reads.
_QUANTILE_COLUMN = {80: "q80", 90: "q90", 95: "q95"}


def _baseline_run(db: Session, forecast_run_id: str | None) -> ForecastRun:
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
            "No completed forecast run exists to build a scenario against.",
            remediation="POST /api/forecasts/runs first.",
        )
    return run


def evaluate(
    db: Session,
    *,
    forecast_run_id: str | None = None,
    name: str = "Scenario",
    demand_multiplier: float = 1.0,
    service_level: int = 95,
    lead_time_days: float | None = None,
    review_period_days: int | None = None,
    scope_level: str = "branch",
    scope_keys: Sequence[str] | None = None,
    period: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Baseline versus scenario, row by row, with the levers stated.

    Computed on read rather than stored: the baseline rows are immutable, the
    levers are a handful of scalars, and re-deriving is cheaper and more
    auditable than persisting a second copy of every forecast.
    """
    if not MULTIPLIER_BOUNDS[0] <= demand_multiplier <= MULTIPLIER_BOUNDS[1]:
        raise ValidationFailedError(
            f"A demand multiplier of {demand_multiplier} is outside the "
            f"supported range {MULTIPLIER_BOUNDS}.",
            details={"bounds": list(MULTIPLIER_BOUNDS)},
        )
    if service_level not in SERVICE_LEVELS:
        raise ValidationFailedError(
            f"Service level {service_level} is not offered.",
            details={"valid": list(SERVICE_LEVELS)},
        )
    if lead_time_days is not None and lead_time_days < 0:
        raise ValidationFailedError("A negative lead time is not meaningful.")

    settings = get_settings()
    run = _baseline_run(db, forecast_run_id)
    review = (
        settings.review_period_days if review_period_days is None else review_period_days
    )

    conditions = [
        ForecastRow.forecast_run_id == run.id,
        ForecastRow.scope_level == scope_level,
    ]
    if period:
        conditions.append(ForecastRow.period == period)
    if scope_keys:
        conditions.append(ForecastRow.scope_key.in_(list(scope_keys)))
    rows = list(
        db.scalars(
            select(ForecastRow)
            .where(*conditions)
            .order_by(ForecastRow.scope_key, ForecastRow.period)
            .limit(limit)
        )
    )
    if not rows:
        raise NotFoundError(
            f"Forecast run {run.id!r} has no {scope_level}-level rows to build a "
            "scenario from.",
            remediation=(
                "Choose a level the run forecast, or generate forecasts at this "
                "level first."
            ),
        )

    quantile_column = _QUANTILE_COLUMN[service_level]
    items: list[dict[str, Any]] = []
    baseline_total = 0.0
    scenario_total = 0.0
    baseline_orders = 0.0
    scenario_orders = 0.0
    skipped = 0

    for row in rows:
        if row.point_forecast is None:
            skipped += 1
            items.append(
                {
                    "scope_key": row.scope_key,
                    "period": row.period,
                    "horizon": row.horizon,
                    "baseline_point": None,
                    "scenario_point": None,
                    "baseline_quantile": None,
                    "scenario_quantile": None,
                    "baseline_recommended_order": None,
                    "scenario_recommended_order": None,
                    "unavailable_reason": row.unavailable_reason
                    or (
                        "The baseline has no forecast for this scope, so there "
                        "is nothing to scale. A scenario cannot invent one."
                    ),
                }
            )
            continue

        baseline_point = float(row.point_forecast)
        baseline_quantile = getattr(row, quantile_column, None)
        scenario_point = baseline_point * demand_multiplier
        scenario_quantile = (
            float(baseline_quantile) * demand_multiplier
            if baseline_quantile is not None
            else None
        )

        # The order position is recomputed through the same policy the
        # inventory service uses, so a scenario and a recommendation cannot
        # drift apart in their arithmetic.
        baseline_lead = settings.default_lead_time_days
        scenario_lead = baseline_lead if lead_time_days is None else lead_time_days

        def _order(quantile: float | None, point: float, lead: float, review_days: int):
            if quantile is None:
                return None
            outcome = recommend(
                InventoryInputs(
                    scope_key=row.scope_key,
                    canonical_branch=row.canonical_branch,
                    canonical_sku=row.canonical_sku,
                    monthly_quantile_forecast=quantile,
                    monthly_point_forecast=point,
                    service_level=service_level,
                    review_period_days=review_days,
                    lead_time_days=lead,
                    # A scenario compares demand positions, so stock is held at
                    # zero on both sides rather than guessed - the difference
                    # between the two columns is then attributable to the levers
                    # alone.
                    usable_stock_on_hand=0.0,
                ),
                apply_moq=False,
            )
            return outcome.recommended_order

        baseline_order = _order(
            None if baseline_quantile is None else float(baseline_quantile),
            baseline_point,
            baseline_lead,
            settings.review_period_days,
        )
        scenario_order = _order(scenario_quantile, scenario_point, scenario_lead, review)

        baseline_total += baseline_point
        scenario_total += scenario_point
        baseline_orders += baseline_order or 0.0
        scenario_orders += scenario_order or 0.0

        items.append(
            {
                "scope_key": row.scope_key,
                "period": row.period,
                "horizon": row.horizon,
                "model_id": row.model_id,
                "baseline_point": baseline_point,
                "scenario_point": scenario_point,
                "baseline_quantile": baseline_quantile,
                "scenario_quantile": scenario_quantile,
                "baseline_recommended_order": baseline_order,
                "scenario_recommended_order": scenario_order,
                "unavailable_reason": None,
            }
        )

    return {
        "name": name,
        "generated_at": datetime.now(timezone.utc),
        "baseline_forecast_run_id": run.id,
        "baseline_origin_period": run.origin_period,
        "scope_level": scope_level,
        "period": period,
        "levers": {
            "demand_multiplier": demand_multiplier,
            "service_level": service_level,
            "lead_time_days": lead_time_days,
            "baseline_lead_time_days": settings.default_lead_time_days,
            "review_period_days": review,
            "baseline_review_period_days": settings.review_period_days,
        },
        "totals": {
            "baseline_demand": baseline_total,
            "scenario_demand": scenario_total,
            "demand_delta": scenario_total - baseline_total,
            "demand_delta_pct": (
                (scenario_total - baseline_total) / baseline_total * 100.0
                if baseline_total
                else None
            ),
            "baseline_order_quantity": baseline_orders,
            "scenario_order_quantity": scenario_orders,
            "order_delta": scenario_orders - baseline_orders,
            "order_delta_pct": (
                (scenario_orders - baseline_orders) / baseline_orders * 100.0
                if baseline_orders
                else None
            ),
        },
        "rows": items,
        "rows_returned": len(items),
        "rows_without_baseline": skipped,
        "caveats": [
            "The baseline forecast run is read-only: a scenario is computed on "
            "read from the stored rows and never written back over them.",
            "Stock on hand is held at zero on both sides of the comparison, so "
            "the difference between the two order columns is attributable to "
            "the levers alone. For a real order position use "
            "GET /api/inventory/recommendations.",
            "A demand multiplier scales the point forecast and its quantiles "
            "together. It does not re-fit any model, so it cannot tell you "
            "whether the scaled demand is plausible - only what it would imply.",
            f"Order quantities use protection period = review + lead time over "
            f"{DAYS_PER_MONTH:g} days per month, the same policy the inventory "
            "service applies.",
        ],
    }
