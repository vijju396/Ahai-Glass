"""The LLM layer: the system prompt, the client, and the no-key answer path.

Two paths produce an answer, and both are constrained to the same facts:

- **With a key**, `agent.py` runs OpenAI function-calling — the model picks
  which AIS tools to call, the tools run here in the backend, and a second
  call turns their output into prose.
- **With no key, or when the provider fails**, `compose_answer` below writes
  the same answer deterministically from the same facts. It is labelled in the
  response as a deterministic answer, because a reader deserves to know
  whether a sentence was written by a model or by a template.

Neither path is ever allowed to produce a number that is not already in the
facts. That is what the grounding rules in the prompt are for, and it is also
why `compose_answer` exists at all: a fallback that invented text would defeat
the point of having one.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Enough turns for a follow-up to resolve, short enough that the facts stay
#: the dominant part of the prompt.
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 500
MAX_ANSWER_CHARS = 1400

SYSTEM_PROMPT = """You are the demand and inventory assistant for AIS Glass Forecast &
Inventory Intelligence — Asahi India Glass's Consumer Glass Solutions network: 53 branches,
about 2,300 SKUs, forecast at branch x SKU x month. Each turn you are given structured facts
the application already computed from its own data: ordered-demand history, model error,
stored forecasts with service-level quantiles, supply exceptions, replenishment
recommendations, and data-quality signals.

GROUNDING
1. Use ONLY the numbers in the provided facts. Never invent, estimate, re-derive or
   round-together a figure, a forecast, a rank or a saving. If you find yourself about to do
   arithmetic, stop: the facts already contain the computed answer.
2. If the facts do not contain what was asked, say so in one line and name what is missing.
   Never fill the hole with a plausible number.
3. Carry the unit every time. Demand is units, value is rupees (write ₹8.9Cr or ₹12.4L in
   Indian numbering), error is a percentage, cover is days, lead time is days.
4. Ordered quantity is the demand target. A `sales_proxy` row is a labelled substitute for
   it, never the same measurement — if a fact says a window mixes the two, say so.
5. A censored row means despatch fell short of the order, so the ordered figure is a LOWER
   BOUND on true demand. Never describe a censored actual as the demand.
6. q80/q90/q95 are service-level demand quantities, not a symmetric confidence interval.
   q95 is the level demand is not expected to exceed 95% of the time. Never call them a
   confidence band and never present one as "the forecast".
7. A point forecast in these facts is post-reconciliation. Where the facts give a
   pre-reconciliation value and an adjustment, keep them distinct — never add them together
   or present the adjustment as part of the forecast.
8. Lists are already sorted and the field name says how (for example
   `branches_ranked_by_demand`). The first row answers "highest" or "worst" — do not
   re-rank by eye.
9. Stock figures come from a single snapshot dated 2026-08-01 while demand history ends
   2026-07. Anything derived from stock is a current-snapshot estimate; say so, and never
   describe it as a trend.
10. `naive`, `seasonal_naive`, `ma3` and `ma6` are baselines, never one of the 13 registered
   models, and can never be champion. If a baseline beats the champion, say that plainly —
   it is a real and important finding, not something to soften.
11. A model that did not run has a status — Ineligible, Failed, Timed out, Not evaluated
   (budget) — and a reason. Report the reason. Never describe such a model as having an
   error of zero, and never leave it out of a "which model is best" answer.
12. Aggregate (national, region, branch) error does not transfer to a single branch x SKU
   cell: aggregates are far less intermittent and much easier to forecast. If a fact says
   the scope is an aggregate, do not present its accuracy as the accuracy of a cell.
13. A short follow-up ("why?", "and Bengaluru?") refers to the previous turn. Carry that
   subject forward instead of asking the user to repeat it.

SCOPE
Stay inside this application's domain: demand history and forecasts, model performance and
champion selection, stock cover and replenishment, supply and data exceptions, drift and
data quality. For anything else, decline briefly and point back to those topics.

TOOLS
You have tools that fetch real AIS data. Call whichever are needed — one is usually enough,
rarely more than two. Never answer a data question from memory. If no tool genuinely applies,
the question is out of scope: decline rather than guessing at a tool.

If the user asks to see a chart, graph or trend, that is not a separate capability — it means
the same underlying data, which the application renders as a chart itself once you call the
relevant tool. Call the tool that matches the subject and answer normally in words.

FORMAT
- Open with ONE short sentence that answers the question directly, with the deciding number
  in it.
- Then up to 4 bullet lines, each starting '- ' and a short bolded label, for example:
  - **Fill rate** - 82.0% across the window, with 1.14 M proxy months excluded.
  Every bullet carries a real figure from the facts.
- Where the facts support a specific action, finish with one line starting '**Next step:** '.
  Never begin it with Continue, Monitor, Keep, Maintain or Ensure — if that is all you have,
  leave the line out. A factual question usually needs no next step.
- Only '- ' bullets and **bold**. No headings, no tables, no numbered lists.
- Stay under 150 words. Specific and calm; no filler."""

SCOPE_MESSAGE = """That one is outside what I can see — I only read this application's own
demand, forecast and inventory data.

**I can help with**
- Ordered-demand history and where demand is heading
- The 13 registered models, their measured error, and which is champion
- Stored forecasts for horizons 1-6, with q80/q90/q95 service levels
- Stock cover, replenishment recommendations and their inputs
- Supply and data exceptions — short despatch, zero stock against live demand
- Data freshness, input drift and whether error deterioration is computable yet

**Try**
- "Show the monthly demand trend"
- "Which branches hold dead or slow stock?\""""

GREETING_MESSAGE = """Hello. I am the demand and inventory assistant for this AIS Glass
build, and every number I give you is read from this application's own data — 53 branches,
about 2,300 SKUs, forecast at branch x SKU x month.

**What I can tell you about**
- **Demand** - ordered-demand history by branch, SKU and month, and where it is heading
- **Models** - all 13 registered models, their measured error, and why one is champion
- **Forecasts** - horizons 1-6 with q80/q90/q95 service levels and their provenance
- **Stock** - cover, replenishment recommendations, dead and slow stock
- **Exceptions** - short despatch, zero stock against live demand, data defects
- **Trust** - freshness, drift, and what is not yet computable

**A good place to start**
- "Show the monthly demand trend"
- "Explain why this model is champion"
- "Which SKUs have zero stock and live demand?\""""


def is_configured() -> bool:
    """Whether a real OpenAI call is possible."""
    settings = get_settings()
    return bool(settings.ai_assistant_enabled and settings.openai_api_key)


def setup_instructions() -> dict[str, Any]:
    """What an operator has to do to switch the assistant on.

    Returned by `/api/assistant/status` so the page can show the steps instead
    of a dead input box. Deliberately never echoes the key or its length.
    """
    settings = get_settings()
    return {
        "enabled": bool(settings.ai_assistant_enabled),
        "configured": is_configured(),
        "model": settings.openai_model,
        "steps": [
            "Open backend/.env (it already exists, with OPENAI_API_KEY blank).",
            "Paste your OpenAI API key after OPENAI_API_KEY= and save.",
            "Restart the backend so the setting is re-read.",
        ],
        "notes": [
            "The key stays on the server. It is never sent to the browser, never "
            "placed in a VITE_ variable, never logged and never returned by any endpoint.",
            "Without a key the assistant still answers from the application's own data "
            "using a deterministic writer, and every other page works normally.",
            "Only small aggregate figures are ever sent to OpenAI - never a source file, "
            "a raw row, or any customer, GSTIN, PAN, address, email or phone value.",
        ],
    }


def client():
    """A timeout-bounded OpenAI client."""
    from openai import OpenAI

    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.ai_request_timeout_seconds, max_retries=1)


def history_messages(history: list[dict] | None) -> list[dict]:
    """Prior turns, trimmed. Assistant turns are truncated because the model
    only needs to know what it already said, not to re-read every figure."""
    messages: list[dict] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        messages.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
    return messages


# ----------------------------------------------------------------------
# Deterministic writer
# ----------------------------------------------------------------------

_LABELS: dict[str, str] = {
    "demand_trend": "Demand",
    "branch_demand": "Branches",
    "model_leaderboard": "Models",
    "forecast_outlook": "Forecast",
    "stock_exceptions": "Exceptions",
    "inventory_recommendations": "Replenishment",
    "data_quality": "Data",
}


def compose_answer(question: str, facts: dict[str, dict[str, Any]]) -> str:
    """Write the answer from the facts, without a model.

    Used when no key is configured and when the provider fails. It reads the
    same dicts the model would have read and states the headline figures, so
    the application is useful with no credentials at all — and so the fallback
    can never contradict the charts beside it.
    """
    if not facts:
        return SCOPE_MESSAGE

    lines: list[str] = []
    lead: str | None = None

    for name, payload in facts.items():
        if not isinstance(payload, dict) or payload.get("status"):
            note = payload.get("status") if isinstance(payload, dict) else None
            if note:
                lines.append(f"- **{_LABELS.get(name, name)}** - {note}")
            continue

        if name == "demand_trend":
            lead = (
                f"Ordered demand for {payload.get('scope')} is {payload.get('direction')}: "
                f"{payload.get('latest_demand_units'):,.0f} units in {payload.get('latest_month')}."
            )
            lines.append(
                f"- **Window** - {payload['window']['periods']} months, "
                f"{payload['window']['start']} to {payload['window']['end']}, "
                f"mean {payload.get('mean_monthly_units'):,.0f} units/month."
            )
            if payload.get("change_pct") is not None:
                lines.append(
                    f"- **Change** - {payload['change_pct']:+.1f}% from first month to last, "
                    f"peak {payload.get('peak')}, trough {payload.get('trough')}."
                )
            if payload.get("fill_rate_pct") is not None:
                lines.append(f"- **Fill rate** - {payload['fill_rate_pct']}% of ordered units despatched.")

        elif name == "branch_demand":
            rows = payload.get("branches_ranked_by_demand") or []
            if rows:
                top = rows[0]
                lead = lead or (
                    f"{top['branch']} is the largest branch by ordered demand at "
                    f"{top['units']:,.0f} units."
                )
                lines.append(
                    "- **Top three** - "
                    + ", ".join(f"{r['branch']} {r['units']:,.0f}" for r in rows[:3])
                    + " units."
                )
                lines.append(f"- **Coverage** - {payload.get('branches_total')} branches in the panel.")

        elif name == "model_leaderboard":
            champion = payload.get("champion")
            if champion:
                lead = lead or (
                    f"{champion['model']} is champion at national scope with a WAPE of "
                    f"{champion['wape_pct']}%."
                )
                lines.append(
                    f"- **Champion** - {champion['model']}, WAPE {champion['wape_pct']}%, "
                    f"{champion['validation_points']} validation points."
                )
            baseline = payload.get("best_baseline")
            if baseline:
                verdict = "beats" if payload.get("champion_beats_best_baseline") else "loses to"
                lines.append(
                    f"- **Versus baseline** - the champion {verdict} {baseline['method']} "
                    f"at WAPE {baseline['wape_pct']}%."
                )
            missing = payload.get("models_that_did_not_run") or []
            if missing:
                lines.append(
                    f"- **Did not run** - {len(missing)} of 13, including "
                    f"{missing[0]['model']} ({missing[0]['status']})."
                )

        elif name == "forecast_outlook":
            horizons = payload.get("horizons") or []
            if horizons:
                first = horizons[0]
                lead = lead or (
                    f"The next stored forecast is {first['point']:,.0f} units for "
                    f"{first['period']} at national scope."
                )
                lines.append(
                    f"- **Service levels** - q80 {first['q80']:,.0f}, q90 {first['q90']:,.0f}, "
                    f"q95 {first['q95']:,.0f} units; these are service levels, not a confidence band."
                )
                lines.append(f"- **Horizons** - {len(horizons)} months stored, from {payload.get('origin_period')}.")

        elif name == "stock_exceptions":
            totals = payload.get("totals") or {}
            lead = lead or (
                f"{totals.get('total_lines', 0):,} branch x SKU lines carry an exception in "
                f"{payload.get('scope')}."
            )
            for row in (payload.get("by_type") or [])[:3]:
                lines.append(f"- **{row['type']}** - {row['lines']:,} lines, {row['units']:,.0f} units.")

        elif name == "inventory_recommendations":
            recs = payload.get("recommendations") or []
            if recs:
                first = recs[0]
                lead = lead or (
                    f"The largest recommended order in {payload.get('scope')} is "
                    f"{first.get('recommended_order')} units for {first.get('sku')} at {first.get('branch')}."
                )
                lines.append(
                    f"- **Inputs** - order-up-to {first.get('order_up_to_level')}, "
                    f"q95 {first.get('quantile_forecast_per_month')}/month, stock "
                    f"{first.get('stock_on_hand')}, lead time {first.get('lead_time_days')} d."
                )
            lines.append("- **Basis** - a current-snapshot estimate; stock is one snapshot, not a history.")

        elif name == "data_quality":
            drift = payload.get("drift") or {}
            fresh = payload.get("freshness") or {}
            lead = lead or (
                f"Demand history ends {fresh.get('demand_history_end')} and the stock snapshot "
                f"is dated {fresh.get('stock_snapshot_date')}."
            )
            if drift.get("national_shift_pct") is not None:
                lines.append(
                    f"- **Drift** - national demand shifted {drift['national_shift_pct']:.1f}% over the "
                    f"last {drift.get('window_months')} months."
                )
            if drift.get("target_source_changed"):
                lines.append("- **Caveat** - part of that shift is a change of measurement, not of demand.")
            det = payload.get("error_deterioration") or {}
            if det.get("computable") is False:
                lines.append("- **Deterioration** - not computable yet: no forecast month has been observed.")

    if lead is None:
        return SCOPE_MESSAGE
    answer = "\n".join([lead, *lines[:4]])
    return answer[:MAX_ANSWER_CHARS]
