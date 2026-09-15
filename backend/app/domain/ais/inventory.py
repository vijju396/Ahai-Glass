"""Inventory recommendation: the calculation, with its inputs exposed.

The policy is `docs/AIS_DOMAIN_RULES.md` §4:

```
protection_period_days = review_period_days + replenishment_lead_time_days
protection_months      = protection_period_days / 30.4375
order_up_to_level      = quantile_forecast(service_level) scaled to protection_months
recommended_order      = order_up_to_level
                       - usable_stock_on_hand
                       - confirmed_stock_on_order
                       + backorders
```

Four things this module is deliberate about:

**It returns the inputs, not just the answer.** A planner who cannot see which
lead time, which service level and which stock figure produced a number has no
way to challenge it, and a recommendation nobody can challenge is one nobody
should act on.

**It never invents a missing input.** No forecast, no stock record, no lead
time - each produces an `unavailable_reason` and a `None` recommendation, never
a zero. "Order nothing" and "we could not work out what to order" are different
instructions.

**Scaling a monthly forecast to a protection period is stated, not hidden.** The
quantile forecast is a *monthly* quantity; the protection period is usually a
fraction of a month (3-day lead time + 30-day review = 33 days = 1.08 months).
The scaling is linear in the mean but **not** in the quantile - a fact recorded
on every row rather than glossed over.

**MOQ, truck quantity and substitution apply only where the source supports
them.** `Replenishment A/B/C` are zero for all 57 branches and are never used;
only 132 of 2,417 SKUs have a substitute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Mean days per month over a Gregorian year. Used to convert a protection
#: period in days into months, and named rather than inlined so the number
#: cannot drift between call sites.
DAYS_PER_MONTH = 30.4375

#: Service levels AIS offers. Outputs of the point forecast, not models.
SERVICE_LEVELS: tuple[int, ...] = (80, 90, 95)

#: Why the monthly-to-protection-period scaling is approximate. Carried onto
#: every row that used it.
SCALING_CAVEAT = (
    "The forecast is a monthly quantity scaled linearly to the protection "
    "period. Linear scaling is exact for the mean but understates a quantile "
    "when the protection period exceeds one month, because forecast error over "
    "two months is not twice the error over one. Treat a protection period well "
    "above one month as a lower bound on the true order-up-to level."
)

#: The single-snapshot limitation, on every row.
SNAPSHOT_CAVEAT = (
    "A current-snapshot estimate. Stock is a single snapshot dated 2026-08-01 "
    "while demand history ends 2026-07; there is no stock or open-order history, "
    "so no historical inventory-policy backtest is claimed."
)


@dataclass
class InventoryInputs:
    """Everything one recommendation is computed from."""

    scope_key: str
    canonical_branch: str | None = None
    canonical_sku: str | None = None

    #: The quantile forecast for the chosen service level, per month.
    monthly_quantile_forecast: float | None = None
    monthly_point_forecast: float | None = None
    service_level: int = 95

    review_period_days: int = 30
    lead_time_days: float | None = None
    lead_time_source: str | None = None
    lead_time_p95_days: float | None = None

    usable_stock_on_hand: float | None = None
    closing_stock_on_hand: float | None = None
    negative_stock_rows: int = 0
    confirmed_stock_on_order: float = 0.0
    backorders: float = 0.0

    moq: float | None = None
    truck_quantity: float | None = None
    case_pack: float | None = None
    substitute_skus: list[str] = field(default_factory=list)

    #: Carried through from the forecast so the recommendation inherits its
    #: caveats rather than shedding them.
    target_source: str | None = None
    is_censored: bool | None = None
    forecast_model_id: str | None = None
    forecast_period: str | None = None
    demand_segment: str | None = None
    stock_class: str | None = None


@dataclass
class InventoryRecommendation:
    """One recommendation, with the arithmetic that produced it."""

    inputs: InventoryInputs
    protection_period_days: float | None = None
    protection_months: float | None = None
    order_up_to_level: float | None = None
    recommended_order: float | None = None
    #: Before MOQ / truck / case-pack rounding, so the rounding is visible.
    raw_recommended_order: float | None = None
    days_of_cover: float | None = None
    unavailable_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        inputs = self.inputs
        return {
            "scope_key": inputs.scope_key,
            "canonical_branch": inputs.canonical_branch,
            "canonical_sku": inputs.canonical_sku,
            "service_level": inputs.service_level,
            "forecast_period": inputs.forecast_period,
            "forecast_model_id": inputs.forecast_model_id,
            "demand_segment": inputs.demand_segment,
            "stock_class": inputs.stock_class,
            "monthly_point_forecast": inputs.monthly_point_forecast,
            "monthly_quantile_forecast": inputs.monthly_quantile_forecast,
            "review_period_days": inputs.review_period_days,
            "lead_time_days": inputs.lead_time_days,
            "lead_time_source": inputs.lead_time_source,
            "lead_time_p95_days": inputs.lead_time_p95_days,
            "protection_period_days": self.protection_period_days,
            "protection_months": self.protection_months,
            "usable_stock_on_hand": inputs.usable_stock_on_hand,
            "closing_stock_on_hand": inputs.closing_stock_on_hand,
            "negative_stock_rows": inputs.negative_stock_rows,
            "confirmed_stock_on_order": inputs.confirmed_stock_on_order,
            "backorders": inputs.backorders,
            "order_up_to_level": self.order_up_to_level,
            "raw_recommended_order": self.raw_recommended_order,
            "recommended_order": self.recommended_order,
            "days_of_cover": self.days_of_cover,
            "moq": inputs.moq,
            "truck_quantity": inputs.truck_quantity,
            "case_pack": inputs.case_pack,
            "substitute_skus": list(inputs.substitute_skus),
            "target_source": inputs.target_source,
            "is_censored": inputs.is_censored,
            "unavailable_reason": self.unavailable_reason,
            "warnings": list(self.warnings),
            "caveats": list(self.caveats),
            "is_current_snapshot_estimate": True,
        }


def recommend(
    inputs: InventoryInputs,
    *,
    apply_moq: bool = True,
    default_lead_time_days: float | None = None,
) -> InventoryRecommendation:
    """One branch x SKU recommendation.

    Refuses rather than guesses. A missing forecast, a missing stock record or a
    missing lead time each produce a stated reason and no number, because each
    one changes the answer and none of them has a safe default.
    """
    result = InventoryRecommendation(inputs=inputs, caveats=[SNAPSHOT_CAVEAT])

    if inputs.monthly_quantile_forecast is None:
        result.unavailable_reason = (
            f"No q{inputs.service_level} forecast exists for {inputs.scope_key}, "
            "so there is no demand figure to size an order against. Nothing was "
            "substituted."
        )
        return result

    lead_time = inputs.lead_time_days
    if lead_time is None and default_lead_time_days is not None:
        lead_time = default_lead_time_days
        result.warnings.append(
            f"No branch lead time was recorded, so the network default of "
            f"{default_lead_time_days:g} days was used. The recommendation is "
            "only as good as that assumption."
        )
    if lead_time is None:
        result.unavailable_reason = (
            f"No replenishment lead time is available for "
            f"{inputs.canonical_branch or inputs.scope_key}, so the protection "
            "period cannot be computed."
        )
        return result

    if inputs.usable_stock_on_hand is None:
        result.unavailable_reason = (
            f"No stock record exists for {inputs.scope_key} in the 2026-08-01 "
            "snapshot. Treating absent stock as zero would recommend a full "
            "order-up-to quantity for an item that may be fully stocked."
        )
        return result

    protection_days = float(inputs.review_period_days) + float(lead_time)
    protection_months = protection_days / DAYS_PER_MONTH
    result.protection_period_days = protection_days
    result.protection_months = protection_months

    order_up_to = float(inputs.monthly_quantile_forecast) * protection_months
    result.order_up_to_level = order_up_to
    if protection_months > 1.0:
        result.caveats.append(SCALING_CAVEAT)

    raw = (
        order_up_to
        - float(inputs.usable_stock_on_hand)
        - float(inputs.confirmed_stock_on_order)
        + float(inputs.backorders)
    )
    result.raw_recommended_order = raw

    # A negative requirement means the position is already long. Reported as
    # zero to order, with the surplus named, rather than as a negative order.
    if raw <= 0:
        result.recommended_order = 0.0
        result.warnings.append(
            f"Stock on hand and on order already cover the protection period by "
            f"{abs(raw):,.0f} units, so no order is recommended."
        )
    else:
        result.recommended_order = _apply_rounding(raw, inputs, result, apply_moq)

    monthly = inputs.monthly_point_forecast or inputs.monthly_quantile_forecast
    if monthly and monthly > 0:
        result.days_of_cover = (
            float(inputs.usable_stock_on_hand) / monthly * DAYS_PER_MONTH
        )
    elif inputs.usable_stock_on_hand and inputs.usable_stock_on_hand > 0:
        result.days_of_cover = None
        result.warnings.append(
            "Stock is held but the forecast is zero, so days of cover is "
            "undefined rather than infinite. This is a placement question, not a "
            "replenishment one."
        )

    if inputs.negative_stock_rows:
        result.warnings.append(
            f"{inputs.negative_stock_rows} negative stock row(s) underlie this "
            "position and are excluded from usable stock. They are a "
            "data-quality exception, not a clamped zero."
        )
    if inputs.is_censored:
        result.warnings.append(
            "The demand history behind this forecast includes censored months - "
            "ordered demand was not fully served - so the true requirement may "
            "be higher than the observed history implies."
        )
    if inputs.target_source == "sales_proxy":
        result.warnings.append(
            "This forecast rests partly on `sales_proxy` history, a labelled "
            "substitute for ordered quantity rather than the same measure."
        )
    if inputs.substitute_skus:
        result.warnings.append(
            "Substitutes exist ("
            + ", ".join(inputs.substitute_skus)
            + "); their stock is not netted off this recommendation, because the "
            "mapping records interchangeability, not a substitution policy."
        )
    return result


def _apply_rounding(
    raw: float,
    inputs: InventoryInputs,
    result: InventoryRecommendation,
    apply_moq: bool,
) -> float:
    """MOQ, case pack and truck quantity - only where the source has them.

    Applied in that order and each step is recorded, so the difference between
    the arithmetic requirement and the orderable quantity is visible.
    """
    if not apply_moq:
        return raw

    quantity = raw
    if inputs.moq and inputs.moq > 0 and quantity < inputs.moq:
        result.warnings.append(
            f"The requirement of {quantity:,.0f} is below the MOQ of "
            f"{inputs.moq:g}, so the order was raised to the MOQ."
        )
        quantity = float(inputs.moq)
    if inputs.case_pack and inputs.case_pack > 0:
        packs = -(-quantity // inputs.case_pack)
        rounded = packs * float(inputs.case_pack)
        if rounded != quantity:
            result.warnings.append(
                f"Rounded up to {packs:g} case pack(s) of {inputs.case_pack:g}."
            )
        quantity = rounded
    if inputs.truck_quantity and inputs.truck_quantity > 0:
        if quantity < inputs.truck_quantity:
            result.warnings.append(
                f"The order of {quantity:,.0f} is below the truck quantity of "
                f"{inputs.truck_quantity:g}; consolidating with other lines "
                "would improve freight cost. The quantity was not raised, "
                "because ordering stock that is not needed is not a saving."
            )
    return quantity


def days_of_cover(stock: float | None, monthly_demand: float | None) -> float | None:
    """Days the stock on hand covers, or `None` when undefined.

    `None` rather than infinity when demand is zero: an item with stock and no
    demand has no meaningful cover, it has a placement problem.
    """
    if stock is None or monthly_demand is None or monthly_demand <= 0:
        return None
    return stock / monthly_demand * DAYS_PER_MONTH
