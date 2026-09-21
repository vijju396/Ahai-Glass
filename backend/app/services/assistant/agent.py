"""OpenAI function-calling: the model chooses which AIS tools to run.

The loop is deliberately small and bounded. The model is given the tool
*names* and nothing to parameterise — every tool takes its scope from the
server-resolved `scope` dict, never from a model-authored argument, so there
is nothing here for a model to get wrong about *what* to fetch, only about
*which* fetch is relevant.

That is the security boundary as much as the correctness one: a model that
could author tool arguments could ask for a scope the user is not looking at,
and a model that could author chart data could draw something the facts do not
support. It can do neither.

`service.ask()` catches everything this raises — including "the model called
no tools at all", raised explicitly below — and falls back to the
deterministic writer, so a provider outage degrades the prose rather than
breaking the request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.assistant import llm, tools
from app.services.assistant import quality

logger = logging.getLogger(__name__)

#: One round answers almost every question. A second covers a follow-on need
#: the first round's results reveal. Capped low: every round is a full
#: round-trip to the provider.
MAX_ROUNDS = 2
#: Across all rounds combined, so a pathological reply cannot spend an
#: unbounded number of database queries in one request.
MAX_TOOL_CALLS = 3
#: The tool-selecting turn only ever emits `{}` as arguments, so it needs
#: almost no output budget.
SELECTION_MAX_TOKENS = 80


def _schema() -> list[dict[str, Any]]:
    """One zero-argument function per tool.

    No parameters at all is the point: scoping is resolved deterministically
    in `tools.resolve_scope` from the question and the previous turn, and
    letting the model paraphrase a branch name into an argument would bypass
    that validation entirely.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
        for name, description in tools.TOOL_DESCRIPTIONS.items()
    ]


def _assistant_message(message: Any) -> dict[str, Any]:
    """Hand-built rather than `model_dump()`.

    The SDK's pydantic dump carries fields that vary by version (refusal,
    audio, annotations); resubmitting an unfamiliar shape on the next call is
    an avoidable failure mode.
    """
    return {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in (message.tool_calls or [])
        ],
    }


def _tool_message(call_id: str, facts: dict[str, Any]) -> dict[str, Any]:
    """A tool result, minus the chart.

    The model never needs the data array to write a sentence about a number,
    and it costs real tokens — so the chart is stripped before the facts enter
    the prompt. It still reaches the client, straight from the tool.
    """
    payload = {key: value for key, value in facts.items() if key != "chart"}
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(payload, default=str, ensure_ascii=False)[:12_000],
    }


def run(
    db: Session,
    question: str,
    history: list[dict] | None,
    scope: dict[str, Any],
    *,
    visual: bool,
    chart_type: str | None,
) -> dict[str, Any]:
    """Select tools, run them, and have the model narrate the results."""
    settings = get_settings()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": llm.SYSTEM_PROMPT},
        *llm.history_messages(history),
        {"role": "user", "content": question[:2000]},
    ]
    schema = _schema()
    executed: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()

    for _round in range(MAX_ROUNDS):
        response = llm.client().chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            tools=schema,
            tool_choice="auto",
            # Not `settings.ai_temperature`: this call picks tools, not words.
            temperature=settings.ai_tool_choice_temperature,
            max_tokens=SELECTION_MAX_TOKENS,
        )
        message = response.choices[0].message
        if not message.tool_calls:
            # A tool-call-free reply is never trusted as the final answer: it
            # means either laziness or an ungrounded decline. Either way this
            # falls through to the deterministic writer rather than returning
            # unverified text.
            break

        messages.append(_assistant_message(message))
        for index, call in enumerate(message.tool_calls):
            name = call.function.name
            # Every tool_call_id needs exactly one role:"tool" reply — including
            # the ones we decline to run — or the next create() call rejects the
            # conversation shape.
            if name in seen:
                messages.append(_tool_message(call.id, {"note": "already retrieved this turn"}))
                continue
            if name not in tools.TOOLS or index >= MAX_TOOL_CALLS - len(executed):
                messages.append(_tool_message(call.id, {"skipped": "tool budget exceeded"}))
                continue
            try:
                facts = tools.TOOLS[name](db, scope, visual=visual, chart_type=chart_type)
            except Exception as exc:  # noqa: BLE001 - one tool must not fail the turn
                logger.warning("assistant tool %s failed: %s", name, exc)
                facts = {"status": "This data source is temporarily unavailable."}
            executed.append((name, facts))
            seen.add(name)
            messages.append(_tool_message(call.id, facts))
        if len(executed) >= MAX_TOOL_CALLS:
            break

    if not executed:
        raise RuntimeError("assistant agent selected no tools")

    final = llm.client().chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=settings.ai_temperature,
        max_tokens=settings.ai_max_output_tokens,
    )
    answer = (final.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("assistant agent produced an empty answer")

    # The same coherence guard the drift explanation uses (D-061). It was only
    # ever wired to that one path, so the assistant published whatever the
    # provider returned - and at temperature 2.0 that included answers mixing
    # Korean, Hebrew, Tamil, Cyrillic and Arabic into a sentence about monthly
    # demand. The guard rejects that text correctly; nothing was asking it to.
    #
    # Raising here rather than returning degraded prose: the caller already
    # catches and falls through to the deterministic writer, which answers the
    # same question from the same facts in plain English.
    verdict = quality.check_explanation(
        answer, min_chars=quality.MIN_ANSWER_CHARS
    )
    if not verdict.ok:
        raise RuntimeError(f"assistant answer failed the coherence guard: {verdict.reason}")

    facts_by_tool = {name: facts for name, facts in executed}
    chart = next(
        (facts["chart"] for _name, facts in executed if visual and facts.get("chart")),
        None,
    )
    return {
        "question": question,
        "answer": answer[: llm.MAX_ANSWER_CHARS],
        "tools_used": [name for name, _ in executed],
        "routed_by": "model",
        "answered_by": "openai",
        "facts": {name: {k: v for k, v in facts.items() if k != "chart"} for name, facts in executed},
        "chart": chart,
        "scope": scope,
        "model": settings.openai_model,
    }
