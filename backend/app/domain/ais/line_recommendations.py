"""Per branch x SKU recommendation lines: the facts, and how urgent each one is.

The recommendation page used to answer at the network. "50 branch x SKU lines
are flagged critical" is a count of lines, not a line — a planner cannot act on
it, because it never says *which*. This module keeps the line intact: one
record per branch x SKU, carrying that line's own forecast, stock, cover and
replenishment figures, so a recommendation can name the line it is about
(D-104).

**No arithmetic is invented here.** Every figure is copied from the
recommendation the inventory service already computed and stored. This module
joins, ranks and labels; it does not re-derive an order quantity, and it never
scales a forecast. Where the service could not produce a figure, the field
stays `None` and the line carries the service's own `unavailable_reason` —
never a zero standing in for an unknown.

**Ranking is deterministic and stated.** A model does not decide what is
urgent; `_urgency` does, from measured fields, and the reason it chose that
band travels with the line as `urgency_reason`. A model is asked only to
explain a line that this module has already ranked. That way the ordering is
reproducible between runs and auditable against the page, which a
model-chosen order would not be.
"""

from __future__ import annotations

import math
from typing import Any

#: Bands, most urgent first. `cannot_recommend` is deliberately not a severity
#: on the same axis as the others: a line the service could not serve is an
#: absence of a recommendation, not a mild one, and collapsing the two would
#: hide exactly the thing the status vocabulary exists to keep separate.
CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
CANNOT_RECOMMEND = "cannot_recommend"

_ORDER = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, CANNOT_RECOMMEND: 3}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _urgency(item: dict[str, Any]) -> tuple[str, str]:
    """The band and the sentence saying why, from measured fields only.

    The order of these tests is the point. A line with no usable stock and live
    demand is already failing; a line that runs out before its replenishment
    can arrive is failing next; a line that merely needs an order is neither.
    Testing cover before stock would let a zero-stock line whose cover happens
    to be null fall through to `medium`.
    """
    if item.get("unavailable_reason"):
        return CANNOT_RECOMMEND, str(item["unavailable_reason"])

    usable = _number(item.get("usable_stock_on_hand"))
    quantile = _number(item.get("monthly_quantile_forecast"))
    cover = _number(item.get("days_of_cover"))
    protection = _number(item.get("protection_period_days"))
    order = _number(item.get("recommended_order"))

    if usable is not None and usable <= 0 and quantile is not None and quantile > 0:
        return (
            CRITICAL,
            f"No usable stock against a q{int(item.get('service_level') or 95)} "
            f"planning demand of {quantile:,.0f} units a month.",
        )
    if cover is not None and protection is not None and cover < protection:
        return (
            HIGH,
            f"{cover:,.0f} days of cover against a {protection:,.0f}-day protection "
            "period, so stock runs out before a replenishment ordered today arrives.",
        )
    if order is not None and order > 0:
        return (
            MEDIUM,
            f"Cover is adequate today; the recommended order of {order:,.0f} units "
            "keeps it that way.",
        )
    return (
        MEDIUM,
        "No order is recommended for this line at the current snapshot.",
    )


def build_lines(
    recommendations: list[dict[str, Any]],
    *,
    exception_lines: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """One record per branch x SKU, ranked, with its own evidence.

    `exception_lines` is the exceptions payload's own per-line list, joined on
    branch and SKU so a line can say it was also short-despatched. A line with
    no exception is not thereby healthy — it is a line with no exception — so
    the field is an empty list rather than a claim.

    `limit` trims after ranking, never before, so the most urgent lines survive
    the cut. The count that was trimmed is the caller's to report.
    """
    by_line: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in exception_lines or []:
        branch = str(row.get("branch") or "").strip().upper()
        sku = str(row.get("sku") or "").strip().upper()
        if branch and sku:
            by_line.setdefault((branch, sku), []).append(row)

    built: list[dict[str, Any]] = []
    for item in recommendations:
        branch = str(item.get("canonical_branch") or "").strip()
        sku = str(item.get("canonical_sku") or "").strip()
        if not branch or not sku:
            continue
        urgency, reason = _urgency(item)
        exceptions = by_line.get((branch.upper(), sku.upper()), [])
        built.append(
            {
                "scope_key": item.get("scope_key") or f"{branch}|{sku}",
                "branch": branch,
                "sku": sku,
                "urgency": urgency,
                "urgency_reason": reason,
                "forecast_period": item.get("forecast_period"),
                "service_level": item.get("service_level"),
                "point_forecast": _number(item.get("monthly_point_forecast")),
                "quantile_forecast": _number(item.get("monthly_quantile_forecast")),
                "usable_stock": _number(item.get("usable_stock_on_hand")),
                "on_order": _number(item.get("confirmed_stock_on_order")),
                "backorders": _number(item.get("backorders")),
                "days_of_cover": _number(item.get("days_of_cover")),
                "lead_time_days": _number(item.get("lead_time_days")),
                "protection_period_days": _number(item.get("protection_period_days")),
                "order_up_to_level": _number(item.get("order_up_to_level")),
                "recommended_order": _number(item.get("recommended_order")),
                "model": item.get("forecast_model_id"),
                "demand_segment": item.get("demand_segment"),
                # Carried, never softened. A censored line's ordered quantity is
                # a lower bound on demand, so its forecast is built on an
                # understatement and the reader has to be told.
                "is_censored": bool(item.get("is_censored")),
                "target_source": item.get("target_source"),
                "unavailable_reason": item.get("unavailable_reason"),
                "exceptions": [
                    {"type": e.get("label") or e.get("type"), "units": _number(e.get("units"))}
                    for e in exceptions
                ],
            }
        )

    built.sort(
        key=lambda line: (
            _ORDER[line["urgency"]],
            # Within a band, the bigger exposure first. A null order sorts last
            # rather than as zero.
            -(line["recommended_order"] if line["recommended_order"] is not None else -1),
            line["branch"],
            line["sku"],
        )
    )
    return built[:limit] if limit else built


def counts(lines: list[dict[str, Any]]) -> dict[str, int]:
    """How many lines fell in each band, so a trimmed list can say what it hid."""
    tally = {CRITICAL: 0, HIGH: 0, MEDIUM: 0, CANNOT_RECOMMEND: 0}
    for line in lines:
        tally[line["urgency"]] = tally.get(line["urgency"], 0) + 1
    return tally
