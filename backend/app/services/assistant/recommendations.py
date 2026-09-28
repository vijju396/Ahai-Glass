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
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.ais import line_recommendations
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

#: How many branch x SKU lines get a written recommendation. Ranked first, so
#: the cut keeps the urgent ones; the bands hidden by the cut are reported.
MAX_LINES = 12

#: The network pass's own budget, no longer shared with the Q&A assistant's
#: `ai_max_output_tokens` (900). Five items of title + observation + a 2-4
#: sentence explanation + evidence do not fit in 900 tokens: the JSON was
#: truncated mid-string at ~3,480 characters, the parse raised, and the page
#: fell back to templates on every single call. Raising the shared setting
#: would have changed the assistant's answer length too, which is a different
#: question (D-104).
NETWORK_OUTPUT_TOKENS = 2200

#: The per-line pass needs longer than the shared 30-second request timeout:
#: twelve written items is simply more generation than one answer, and it was
#: timing out and silently falling back to templates. Passed per request so
#: the Q&A assistant keeps its own, shorter timeout - a chat reply that takes
#: 90 seconds is a broken chat (D-104).
LINE_TIMEOUT_SECONDS = 120.0

#: How long a completed pass is reused.
#:
#: This is a standing question over data that only changes when a forecast run
#: or a panel build does, so re-deriving it per page view bought nothing and
#: cost ~35 seconds each time. The key carries both ids, so a new run
#: invalidates it immediately rather than serving yesterday's answer for an
#: hour (D-104).
CACHE_TTL_SECONDS = 900.0

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(db: Session) -> str:
    """Identity of the data a pass was computed from, not of the request.

    Keyed on the newest completed forecast run and panel build. Two callers
    looking at the same data share an answer; the moment either changes, the
    key changes and nothing stale can be served.
    """
    from app.models.forecasts import ForecastRun
    from app.models.panel import PanelBuild

    def newest(model: Any) -> str:
        row = db.scalars(
            select(model)
            .where(model.status == "completed")
            .order_by(model.created_at.desc())
            .limit(1)
        ).first()
        return getattr(row, "id", "none")

    try:
        return f"{newest(ForecastRun)}:{newest(PanelBuild)}"
    except Exception:  # noqa: BLE001 - a cache key must never break the page
        return "unkeyed"


def _cached(key: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
    if not entry:
        return None
    stored_at, payload = entry
    if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
        with _CACHE_LOCK:
            _CACHE.pop(key, None)
        return None
    age = round(time.monotonic() - stored_at)
    return payload | {"cached": True, "cache_age_seconds": age}


def _store(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Only a fully model-written pass is cached.

    Caching a template fallback would pin a provider blip in place for the
    whole TTL, and the page would keep saying the model could not be reached
    long after it could.
    """
    if payload.get("answered_by") == "openai" and payload.get("lines_answered_by") in (
        "openai",
        "no_lines",
    ):
        with _CACHE_LOCK:
            _CACHE[key] = (time.monotonic(), payload)
    return payload | {"cached": False, "cache_age_seconds": 0}

#: A separate, larger budget for the per-line pass.
#:
#: The network pass shares `ai_max_output_tokens` (900). That was already tight
#: for five items and the JSON was being truncated mid-string at ~3,480
#: characters, which failed the parse and dropped the page to templates on
#: every call - an "AI Recommendations" page that had never once been written
#: by the model. Twelve line items need more room again, and giving the two
#: passes one budget would make a long line list starve the network items
#: (D-104).
LINE_OUTPUT_TOKENS = 3000

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


LINE_SYSTEM_PROMPT = """You write one recommendation for ONE branch x SKU line at AIS Glass
Forecast & Inventory Intelligence. You are given lines the application already computed and
already ranked, each with its own figures.

GROUNDING - these override everything else
1. Use ONLY the numbers on the line you are writing about. Never use another line's figures,
   never invent, estimate, re-derive or round-together a figure, and do no arithmetic.
2. Write one item for EVERY line given, in the order given. Do not reorder, merge, split or
   drop a line. The ranking was decided before you saw it.
3. Never aggregate across lines. "50 lines are affected" is exactly the sentence this page
   exists to stop producing. Begin each explanation by naming the branch and the FULL SKU
   code verbatim. "This SKU" is not naming it.
4. `is_censored` true means despatch fell short of the order on this line, so its ordered
   quantity is a LOWER BOUND on real demand and the forecast built on it is understated.
   Say so on those lines; never describe the figure as the demand.
5. `target_source` of `sales_proxy` is a labelled substitute for ordered demand, not the
   same measurement.
6. q80/q90/q95 are service-level planning quantities, not a confidence interval.
7. Stock is one snapshot dated 2026-08-01 while demand history ends 2026-07, so anything
   stock-derived is a current estimate, never a trend.
8. `urgency` and `urgency_reason` were computed by the application. Explain them; do not
   re-rank or contradict them.
9. A line whose `unavailable_reason` is set has NO recommendation. Say what is missing.
   Never substitute a zero or imply an order of nothing.
10. Nothing you write is an instruction to act. There is no inventory-policy backtest in
    this project, so you cannot claim acting would have helped.

EXPLAIN CLEARLY
The reader knows their business, not this application's vocabulary. Spell out terms like
protection period, days of cover, censored demand and service level the first time used.
Short sentences. No filler, no hedging.

OUTPUT
Return STRICT JSON only, in exactly this shape:

{"lines": [{"scope_key": "copied verbatim from the line",
            "headline": "short phrase naming the action or the problem, max 70 chars",
            "explanation": "2-3 sentences in plain language: what is happening on THIS line and why it matters",
            "next_step": "one concrete thing to check for this line, or null",
            "evidence": ["figure taken verbatim from this line", "..."]}]}

One object per line given, same order, nothing else."""


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


def _gather_lines(db: Session) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """The ranked branch x SKU lines, their band counts, and the total before the cut.

    Reads the inventory service directly rather than the assistant tool: the
    tool trims to 12 rows for prompt size, and trimming before ranking would
    decide urgency by whatever order the service happened to return.
    """
    from app.services import inventory_service

    try:
        payload = inventory_service.recommendations(db, branch=None, limit=1000)
    except Exception as exc:  # noqa: BLE001 - the page must still render
        logger.warning("line recommendations unavailable: %s", exc)
        return [], {}, 0

    exception_lines: list[dict[str, Any]] = []
    try:
        from app.domain.ais import analytics as A

        panel, _build, path, scope = tools._panel_and_path(db)
        exceptions = A.cached_exceptions(panel, path, tools._analytics_scope(None))
        if not exceptions.get("empty"):
            exception_lines = exceptions.get("top_lines") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("exception join unavailable: %s", exc)

    ranked = line_recommendations.build_lines(
        payload.get("items") or [], exception_lines=exception_lines
    )
    return ranked[:MAX_LINES], line_recommendations.counts(ranked), len(ranked)


def _deterministic_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-line text from templates, when no model wrote it.

    Reads only fields whose shape `line_recommendations` fixes, so it cannot
    overstate. It restates the line's own measured reason rather than
    inventing a second opinion about it.
    """
    written: list[dict[str, Any]] = []
    for line in lines:
        evidence: list[str] = []
        if line.get("quantile_forecast") is not None:
            evidence.append(
                f"q{int(line.get('service_level') or 95)} planning demand = "
                f"{line['quantile_forecast']:,.0f} units/month"
            )
        if line.get("usable_stock") is not None:
            evidence.append(f"usable stock = {line['usable_stock']:,.0f} units")
        if line.get("days_of_cover") is not None:
            evidence.append(f"days of cover = {line['days_of_cover']:,.0f}")
        if line.get("protection_period_days") is not None:
            evidence.append(
                f"protection period = {line['protection_period_days']:,.0f} days"
            )
        if line.get("recommended_order") is not None:
            evidence.append(f"recommended order = {line['recommended_order']:,.0f} units")

        if line.get("unavailable_reason"):
            explanation = (
                f"No recommendation could be produced for this line. "
                f"{line['unavailable_reason']} Nothing has been substituted, and this is "
                "not the same as a recommended order of zero."
            )
        else:
            explanation = line["urgency_reason"]
            if line.get("is_censored"):
                explanation += (
                    " Despatch fell short of the order on this line, so its ordered "
                    "quantity is a lower bound on real demand and this forecast is "
                    "built on an understatement."
                )
        written.append(
            {
                "scope_key": line["scope_key"],
                "headline": f"{line['branch']} x {line['sku']}",
                "explanation": explanation,
                "next_step": "Open Supply Intelligence and filter to this branch and SKU.",
                "evidence": evidence[:6],
            }
        )
    return written


def _merge_lines(
    ranked: list[dict[str, Any]],
    written: list[dict[str, Any]],
    *,
    by_model: bool = True,
) -> list[dict[str, Any]]:
    """Attach written text to the line it names, by `scope_key`.

    Joined on the key rather than on position: a model that dropped or
    reordered a line would otherwise have its text silently attached to a
    different branch x SKU, which is the worst failure this page could have. A
    line the model did not write about keeps its computed facts and says the
    text is missing, rather than disappearing.
    """
    by_key = {str(item.get("scope_key")): item for item in written}
    merged: list[dict[str, Any]] = []
    for line in ranked:
        text = by_key.get(str(line["scope_key"]))
        merged.append(
            line
            | {
                "headline": (text or {}).get("headline") or f"{line['branch']} x {line['sku']}",
                "explanation": (text or {}).get("explanation"),
                "next_step": (text or {}).get("next_step"),
                "evidence": [str(e) for e in ((text or {}).get("evidence") or [])][:6],
                # `by_model` and not merely "is there text": the template
                # fallback also produces text, and reporting that as
                # model-written is exactly the confusion the flag exists to
                # prevent.
                "written_by_model": by_model and text is not None,
            }
        )
    return merged


def generate(db: Session, *, prose: bool = True) -> dict[str, Any]:
    """The recommendation list, however it had to be produced.

    `prose=False` skips both model calls and returns the computed payload -
    the ranking, every figure and each line's own `urgency_reason` - in about
    six seconds instead of thirty-five. Nothing in it is less accurate: the
    figures and the ranking were never the model's work. Only the wording is
    templated, and `answered_by` says so. The page asks for this first so a
    reader sees real content immediately, then asks again for the written
    version (D-104).
    """
    settings = get_settings()
    facts = _gather(db)
    caveats = _caveats(db)
    ranked, band_counts, total_lines = _gather_lines(db)
    base: dict[str, Any] = {
        "sources": list(SOURCES),
        "facts": facts,
        "caveats": caveats,
        "temperature": settings.ai_temperature,
        "model": None,
        "provider_error": None,
        "line_counts": band_counts,
        "lines_total": total_lines,
        "lines_shown": len(ranked),
    }

    if not prose or not llm.is_configured():
        return base | {
            "items": _deterministic(facts),
            "lines": _merge_lines(ranked, _deterministic_lines(ranked), by_model=False),
            "lines_answered_by": "computed_only" if prose is False else "deterministic_no_key",
            "answered_by": "computed_only" if prose is False else "deterministic_no_key",
            "cached": False,
            "cache_age_seconds": 0,
        }

    cache_key = _cache_key(db)
    hit = _cached(cache_key)
    if hit is not None:
        return hit

    # Both passes at once. They share no state and neither reads the other's
    # result, so running them in sequence only ever added one round trip to
    # the wait - about fourteen seconds of it.
    with ThreadPoolExecutor(max_workers=2) as pool:
        line_future = pool.submit(_write_lines, settings, ranked)
        network = _write_network(settings, facts)
        lines_written, lines_answered_by = line_future.result()

    if network["error"] is not None:
        return _store(
            cache_key,
            base
            | {
                "items": _deterministic(facts),
                "lines": lines_written,
                "lines_answered_by": lines_answered_by,
                "answered_by": "deterministic_after_provider_error",
                # Type only. The message can carry request details, and this
                # is returned to a browser.
                "provider_error": network["error"],
            },
        )

    return _store(
        cache_key,
        base
        | {
            "items": network["items"],
            "lines": lines_written,
            "lines_answered_by": lines_answered_by,
            "answered_by": "openai",
            "model": settings.openai_model,
        },
    )


def _write_network(settings: Any, facts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The network pass, as a value rather than an early return.

    Extracted so it can run beside `_write_lines` in a pool. Returning a dict
    instead of raising keeps the failure handling in `generate`, where the
    line result is also in scope - the two must fail independently, and a
    raise here would have taken the line list with it.
    """
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
            max_tokens=NETWORK_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        items = _clean(payload.get("items"))
        if not items:
            raise ValueError("the model returned no evidenced item")
        return {"items": items, "error": None}
    except Exception as exc:  # noqa: BLE001 - the page must still render
        logger.warning("recommendation generation failed: %s", exc)
        return {"items": [], "error": type(exc).__name__}


def _write_lines(settings: Any, ranked: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Ask the model to explain each ranked line; fall back per pass, not per line.

    A separate call from the network pass on purpose. They have different
    prompts, different output budgets and different failure modes, and one
    failing must not empty the other - the whole point of splitting them is
    that a truncated line list no longer costs the page its network items.
    """
    if not ranked:
        return [], "no_lines"
    try:
        response = llm.client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": LINE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Write one recommendation for each line below, in this order.\n\n"
                        + json.dumps(ranked, default=str)[:14000]
                    ),
                },
            ],
            temperature=settings.ai_temperature,
            max_tokens=LINE_OUTPUT_TOKENS,
            response_format={"type": "json_object"},
            timeout=LINE_TIMEOUT_SECONDS,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        written = [item for item in (payload.get("lines") or []) if isinstance(item, dict)]
        if not written:
            raise ValueError("the model returned no line")
        return _merge_lines(ranked, written), "openai"
    except Exception as exc:  # noqa: BLE001 - the page must still render
        logger.warning("line recommendation generation failed: %s", exc)
        return (
            _merge_lines(ranked, _deterministic_lines(ranked), by_model=False),
            "deterministic_after_provider_error",
        )
