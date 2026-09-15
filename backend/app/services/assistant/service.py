"""Assistant orchestration: one entry point, one fallback, no second copy.

`ask()` resolves scope, then tries the model path and falls back to the
deterministic writer. There is exactly one fallback implementation, used both
when no key is configured and when the provider fails, so the two can never
drift apart — the reference project makes the same point in its own comment and
it is the right call.

Every response says how it was produced (`answered_by`), which tools ran, and
what scope it used. A reader can therefore tell a model-written sentence from a
template-written one, which matters when the subject is a number someone will
act on.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.assistant import llm, tools

logger = logging.getLogger(__name__)


def ask(
    db: Session,
    question: str,
    history: list[dict] | None = None,
    current_scope: dict | None = None,
) -> dict[str, Any]:
    """Answer one question against this application's own data."""
    settings = get_settings()
    question = (question or "").strip()

    if not settings.ai_assistant_enabled:
        return _envelope(
            question,
            "The assistant is switched off for this deployment "
            "(`AI_ASSISTANT_ENABLED=false` in backend/.env).",
            scope=current_scope or tools._EMPTY_SCOPE,
            answered_by="disabled",
        )

    if not question:
        return _envelope(
            question,
            "Ask me about demand, a model, a forecast, stock cover or an exception.",
            scope=current_scope or tools._EMPTY_SCOPE,
            answered_by="validation",
        )

    if tools.is_greeting(question):
        return _envelope(
            question,
            llm.GREETING_MESSAGE,
            scope=current_scope or tools._EMPTY_SCOPE,
            answered_by="static",
        )

    scope = tools.resolve_scope(db, question, current_scope, history)
    visual = tools.wants_visual(question)
    chart_type = tools.wants_chart_type(question) if visual else None

    if llm.is_configured():
        try:
            from app.services.assistant import agent

            return agent.run(db, question, history, scope, visual=visual, chart_type=chart_type)
        except Exception as exc:  # noqa: BLE001 - degrade the prose, not the request
            logger.warning("assistant model path failed, using the deterministic writer: %s", exc)
            return _deterministic(
                db,
                question,
                history,
                scope,
                visual,
                chart_type,
                answered_by="deterministic_after_provider_error",
                provider_error=f"{type(exc).__name__}: {exc}"[:300],
            )

    return _deterministic(
        db, question, history, scope, visual, chart_type, answered_by="deterministic_no_key"
    )


def _deterministic(
    db: Session,
    question: str,
    history: list[dict] | None,
    scope: dict[str, Any],
    visual: bool,
    chart_type: str | None,
    *,
    answered_by: str,
    provider_error: str | None = None,
) -> dict[str, Any]:
    """The one fallback path. Same tools, same facts, keyword-chosen."""
    routing_question = question
    if history and tools.is_follow_up(question):
        previous = " ".join(t.get("content", "") for t in history if t.get("role") == "user")
        routing_question = f"{previous} {question}".strip()

    names = tools.select_tools(routing_question)
    if not names:
        return _envelope(
            question, llm.SCOPE_MESSAGE, scope=scope, answered_by=answered_by, provider_error=provider_error
        )

    facts: dict[str, dict[str, Any]] = {}
    for name in names:
        try:
            facts[name] = tools.TOOLS[name](db, scope, visual=visual, chart_type=chart_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant tool %s failed: %s", name, exc)
            facts[name] = {"status": "This data source is temporarily unavailable."}

    chart = next((f["chart"] for f in facts.values() if visual and f.get("chart")), None)
    answer = llm.compose_answer(question, facts)
    return {
        "question": question,
        "answer": answer,
        "tools_used": names,
        "routed_by": "keyword",
        "answered_by": answered_by,
        "facts": {name: {k: v for k, v in f.items() if k != "chart"} for name, f in facts.items()},
        "chart": chart,
        "scope": scope,
        "model": None,
        "provider_error": provider_error,
    }


def _envelope(
    question: str,
    answer: str,
    *,
    scope: dict[str, Any],
    answered_by: str,
    provider_error: str | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "answer": answer,
        "tools_used": [],
        "routed_by": "none",
        "answered_by": answered_by,
        "facts": {},
        "chart": None,
        "scope": scope,
        "model": None,
        "provider_error": provider_error,
    }


#: Shown on the empty assistant page. Each one is answerable by a real tool
#: against real data — a suggestion the assistant cannot answer is worse than
#: no suggestion.
SUGGESTED_QUESTIONS: tuple[str, ...] = (
    "Show the monthly demand trend",
    "Which SKUs have zero stock and live demand?",
    "Explain why this model is champion",
    "Where does a baseline outperform the selected model?",
    "Which branches hold dead or slow stock?",
    "Show actual versus forecast for this branch",
    "Explain the selected inventory recommendation",
)
