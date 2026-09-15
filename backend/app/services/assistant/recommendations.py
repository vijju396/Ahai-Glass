"""AI recommendations: what this application thinks is worth acting on.

The assistant answers questions. This answers the question nobody asked —
*what should I look at?* — by running a fixed set of the same bounded,
read-only tools and asking the model to turn what they return into a short
ranked list, each item explained in plain language.

Three properties this is built around.

**Every recommendation is grounded in a fact the tools returned.** The model
is given the tool output and told to explain it, never to find something new
in it. It cannot query anything, cannot compute anything, and is instructed
that a recommendation it cannot attach a measured figure to must be dropped
rather than softened. `evidence` on each item carries the figures it used, so
a reader can check the claim against the page named in `verify_on`.

**Nothing here is an instruction to act.** Stock is a single snapshot dated
2026-08-01 and there is no inventory-policy backtest to say whether acting on
any of this would have helped (`docs/AIS_DOMAIN_RULES.md`). Items are framed
as things to look at, and the payload says so.

**It works with no API key.** `_deterministic` writes the same list from the
same facts using templates, labelled `answered_by = "deterministic_no_key"`.
A page that goes blank without a key would make the key look mandatory for
data it already has.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.assistant import llm, tools

logger = logging.getLogger(__name__)

#: The tools a recommendation pass runs, in the order their findings are most
#: likely to matter. Fixed rather than model-chosen: this is a standing
#: question, so the same evidence should be gathered every time — a list that
#: changed shape run to run would be impossible to compare against the last one.
SOURCES: tuple[str, ...] = (
    "stock_exceptions",
    "inventory_recommendations",
    "model_leaderboard",
    "forecast_outlook",
    "data_quality",
)

#: Where each source's numbers can be checked. A recommendation the reader
#: cannot go and verify is worth less than one they can.
VERIFY_ON: dict[str, str] = {
    "stock_exceptions": "Operational Exceptions",
    "inventory_recommendations": "Supply Intelligence",
    "model_leaderboard": "Model Leaderboard",
    "forecast_outlook": "Forecast Explorer",
    "data_quality": "Demand Analytics",
}

MAX_ITEMS = 5

#: Kept apart from the ask-a-question prompt: that one answers what was asked,
#: this one decides what is worth raising. The grounding half is repeated
#: rather than referenced because it is the part that must not be lost.
SYSTEM_PROMPT = """You write the recommendation list for AIS Glass Forecast & Inventory
Intelligence — Asahi India Glass's Consumer Glass Solutions network. You are given facts the
application already computed from its own data: supply and data exceptions, replenishment
recommendations, measured model error, stored forecasts, and data-quality signals.

Your job is to pick what is worth a planner's attention and explain each one clearly enough
that someone who has not seen the underlying page understands what it means and why it
matters.

GROUNDING — these override everything else
1. Use ONLY numbers present in the provided facts. Never invent, estimate, re-derive,
   extrapolate or round-together a figure. Do no arithmetic of any kind.
2. If you cannot attach a specific measured figure from the facts to a recommendation, DROP
   it. Do not soften it into a vague suggestion. Fewer, evidenced items is the correct
   outcome; an unevidenced item is a defect.
3. Ordered quantity is the demand target. A `sales_proxy` value is a labelled substitute,
   never the same measurement.
4. A censored row means despatch fell short of the order, so the ordered figure is a LOWER
   BOUND on true demand — never describe it as the demand.
5. q80/q90/q95 are service-level demand quantities, not a confidence interval.
6. Stock comes from a single snapshot dated 2026-08-01 while demand history ends 2026-07.
   Anything stock-derived is a current-snapshot estimate, never a trend.
7. `naive`, `seasonal_naive`, `ma3`, `ma6` are baselines, never one of the 13 registered
   models and never champion. A baseline beating the champion is a real finding — say it
   plainly rather than softening it.
8. A model that did not run has a status (Ineligible, Failed, Timed out, Not evaluated) and
   a reason. Never treat such a model as having zero error.
9. Nothing you write is an instruction to act. There is no inventory-policy backtest in this
   project, so you cannot claim an action would have helped. Frame items as what to look at
   and why.

EXPLAIN CLEARLY
Assume the reader knows their business but not this application's vocabulary. For each item:
- Say what was observed, with the figure.
- Say what it means in plain words — spell out any term like censored demand, WAPE, service
  level or dead stock the first time you use it.
- Say why it matters, concretely (a stockout, an overstated accuracy, a wrong reorder).
- Say what to look at next.
Short sentences. No jargon left unexplained. No filler, no hedging, no motivational language.

OUTPUT
Return STRICT JSON only, no prose outside it, in exactly this shape:

{"items": [{"title": "short noun phrase, max 60 chars",
            "severity": "critical" | "high" | "medium",
            "observation": "one sentence with the deciding figure",
            "explanation": "2-4 sentences in plain language: what it means and why it matters",
            "next_step": "one concrete thing to look at, or null",
            "evidence": ["figure taken verbatim from the facts", "..."],
            "source": "the tool key these facts came from"}]}

At most %d items, most severe first. Fewer is better than padded.""" % MAX_ITEMS


def _gather(db: Session) -> dict[str, dict[str, Any]]:
    """Run every source tool. One failing must not empty the page."""
    facts: dict[str, dict[str, Any]] = {}
    for name in SOURCES:
        fn: Callable[..., dict[str, Any]] | None = tools.TOOLS.get(name)
        if fn is None:  # pragma: no cover - SOURCES is checked by a test
            continue
        try:
            result = fn(db, None, visual=False, chart_type=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("recommendation source %s failed: %s", name, exc)
            facts[name] = {"status": "This data source is temporarily unavailable."}
            continue
        facts[name] = {k: v for k, v in result.items() if k != "chart"}
    return facts


def _caveats(db: Session) -> list[str]:
    """What qualifies the whole list, attached whoever wrote it."""
    from app.domain.ais.workspace import resolve_workspace

    notes = [
        "These are things to look at, not instructions to act. This project has no "
        "inventory-policy backtest, so nothing here can claim that acting would have "
        "helped.",
        "Stock figures come from one snapshot dated 2026-08-01 while demand history ends "
        "2026-07, so anything stock-derived is a current estimate rather than a trend.",
    ]
    scope_note = resolve_workspace(db).note()
    if scope_note:
        notes.insert(0, scope_note)
    return notes


def _clean(items: Any) -> list[dict[str, Any]]:
    """Keep only well-formed, evidenced items, in severity order.

    An item with no evidence is dropped rather than shown: the prompt says a
    recommendation must carry a measured figure, and enforcing that here is
    what makes it true rather than merely requested.
    """
    order = {"critical": 0, "high": 1, "medium": 2}
    cleaned: list[dict[str, Any]] = []
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        observation = str(raw.get("observation") or "").strip()
        explanation = str(raw.get("explanation") or "").strip()
        evidence = [str(e).strip() for e in raw.get("evidence") or [] if str(e).strip()]
        if not (title and observation and explanation and evidence):
            continue
        severity = str(raw.get("severity") or "medium").lower()
        if severity not in order:
            severity = "medium"
        source = str(raw.get("source") or "").strip()
        next_step = raw.get("next_step")
        cleaned.append(
            {
                "title": title[:80],
                "severity": severity,
                "observation": observation[:400],
                "explanation": explanation[:900],
                "next_step": (str(next_step).strip()[:240] or None) if next_step else None,
                "evidence": evidence[:6],
                "source": source if source in SOURCES else None,
                "verify_on": VERIFY_ON.get(source),
            }
        )
    cleaned.sort(key=lambda item: order[item["severity"]])
    return cleaned[:MAX_ITEMS]


def _deterministic(facts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The same list, written from templates, when no model is available.

    Deliberately narrow. It reads only keys whose shape is fixed by the tool
    that produced them, so it can never overstate — and it is labelled
    `deterministic_no_key` in the response, because a reader deserves to know
    whether a sentence was written by a model or by a template.
    """
    items: list[dict[str, Any]] = []

    totals = (facts.get("stock_exceptions") or {}).get("totals") or {}
    critical = totals.get("critical_lines")
    short_despatch = totals.get("short_despatch_lines")
    zero_stock = totals.get("zero_stock_live_demand_lines")
    if isinstance(critical, (int, float)) and critical:
        evidence = [f"critical_lines = {int(critical):,}"]
        if isinstance(short_despatch, (int, float)):
            evidence.append(f"short_despatch_lines = {int(short_despatch):,}")
        if isinstance(zero_stock, (int, float)):
            evidence.append(f"zero_stock_live_demand_lines = {int(zero_stock):,}")
        items.append(
            {
                "title": "Critical supply exceptions are open",
                "severity": "critical",
                "observation": f"{int(critical):,} branch x SKU lines are flagged critical.",
                "explanation": (
                    "A critical exception is a line where despatch fell short of the "
                    "order, or where there was no usable stock while demand was being "
                    "ordered. Short despatch matters twice over: it is a service failure, "
                    "and it also means the recorded order is only a lower bound on what "
                    "was really wanted, so demand on those lines is understated."
                ),
                "next_step": "Open Operational Exceptions and sort by units affected.",
                "evidence": evidence,
                "source": "stock_exceptions",
                "verify_on": VERIFY_ON["stock_exceptions"],
            }
        )

    leaderboard = facts.get("model_leaderboard") or {}
    champion = leaderboard.get("champion") or {}
    best_baseline = leaderboard.get("best_baseline") or {}
    beats = leaderboard.get("champion_beats_best_baseline")
    if beats is False and champion and best_baseline:
        items.append(
            {
                "title": "A baseline is beating the champion model",
                "severity": "high",
                "observation": (
                    f"{best_baseline.get('method')} at {best_baseline.get('wape_pct')}% error "
                    f"is below the champion {champion.get('model')} at "
                    f"{champion.get('wape_pct')}%."
                ),
                "explanation": (
                    "A baseline is a trivial rule, such as repeating last month's figure. "
                    "Error here is WAPE — the total absolute miss as a percentage of total "
                    "demand, so lower is better. A baseline coming in lower means the "
                    "registered model is not earning its complexity on this scope. It is "
                    "reported rather than hidden, and a baseline is never allowed to "
                    "become champion."
                ),
                "next_step": "Compare the scope on the Model Leaderboard.",
                "evidence": [
                    f"champion {champion.get('model')} wape_pct = {champion.get('wape_pct')}",
                    f"baseline {best_baseline.get('method')} wape_pct = {best_baseline.get('wape_pct')}",
                ],
                "source": "model_leaderboard",
                "verify_on": VERIFY_ON["model_leaderboard"],
            }
        )

    drift = (facts.get("data_quality") or {}).get("drift") or {}
    shift = drift.get("national_shift_pct")
    if isinstance(shift, (int, float)):
        items.append(
            {
                "title": "Recent demand has shifted against the earlier history",
                "severity": "medium",
                "observation": (
                    f"National demand has shifted {shift:+.1f}% over the last "
                    f"{drift.get('window_months')} months against the earlier window."
                ),
                "explanation": (
                    "Drift compares recent demand against the history before it. A shift "
                    "is not by itself a fault, but a model fitted before it is being "
                    "measured against a period that no longer resembles its training "
                    "window. Part of this figure is also a change of measurement rather "
                    "than of demand: the earlier window mixes sales-proxy rows while the "
                    "recent window is all orders."
                ),
                "next_step": None,
                "evidence": [
                    f"national_shift_pct = {shift}",
                    f"window_months = {drift.get('window_months')}",
                ],
                "source": "data_quality",
                "verify_on": VERIFY_ON["data_quality"],
            }
        )

    return items[:MAX_ITEMS]


def generate(db: Session) -> dict[str, Any]:
    """The recommendation list, however it had to be produced."""
    settings = get_settings()
    facts = _gather(db)
    caveats = _caveats(db)
    base: dict[str, Any] = {
        "sources": list(SOURCES),
        "facts": facts,
        "caveats": caveats,
        "temperature": settings.ai_temperature,
        "model": None,
        "provider_error": None,
    }

    if not llm.is_configured():
        return base | {
            "items": _deterministic(facts),
            "answered_by": "deterministic_no_key",
        }

    try:
        response = llm.client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Facts computed by the application. Recommend what is worth "
                        "attention, explaining each clearly.\n\n"
                        + json.dumps(facts, default=str)[:14000]
                    ),
                },
            ],
            temperature=settings.ai_temperature,
            max_tokens=settings.ai_max_output_tokens,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        items = _clean(payload.get("items"))
        if not items:
            raise ValueError("the model returned no evidenced item")
    except Exception as exc:  # noqa: BLE001 - the page must still render
        logger.warning("recommendation generation failed: %s", exc)
        return base | {
            "items": _deterministic(facts),
            "answered_by": "deterministic_after_provider_error",
            # Type only. The message can carry request details, and this is
            # returned to a browser.
            "provider_error": type(exc).__name__,
        }

    return base | {
        "items": items,
        "answered_by": "openai",
        "model": settings.openai_model,
    }
