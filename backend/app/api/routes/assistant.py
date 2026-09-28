"""AI assistant endpoints.

`React -> this backend -> OpenAI`. The browser never holds the key and never
talks to OpenAI; it posts a question here and gets back an answer plus the
facts and chart the backend computed.

`/status` exists so the page can render setup instructions rather than a dead
input box when no key is configured. It reports *whether* a key is present and
never any part of its value.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.assistant import llm, recommendations, service

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    #: Prior turns, oldest first, excluding the question being asked. Optional,
    #: and capped: sending it is what makes a follow-up like "why?" resolve.
    history: list[AssistantTurn] = Field(default_factory=list, max_length=12)
    #: The `scope` object from the previous response, round-tripped as-is. Its
    #: shape is backend-defined — the frontend stores and resends it and never
    #: constructs one, so a client cannot widen its own scope.
    current_scope: dict | None = None


class AssistantChartSeries(BaseModel):
    key: str
    label: str
    color: str | None = None


class AssistantChart(BaseModel):
    type: Literal["line", "bar", "pie"]
    title: str
    x_key: str
    series: list[AssistantChartSeries]
    data: list[dict[str, Any]]


class AssistantAnswer(BaseModel):
    question: str
    answer: str
    tools_used: list[str]
    routed_by: str
    #: `openai` | `deterministic_no_key` | `deterministic_after_provider_error`
    #: | `static` | `disabled` | `validation`. Surfaced so the UI can label a
    #: deterministic answer as one rather than implying a model wrote it.
    answered_by: str
    facts: dict[str, Any]
    chart: AssistantChart | None = None
    scope: dict[str, Any]
    model: str | None = None
    provider_error: str | None = None


class Recommendation(BaseModel):
    title: str
    #: critical | high | medium
    severity: str
    observation: str
    explanation: str
    next_step: str | None = None
    #: The figures the item rests on, taken from the tool output. An item that
    #: could not carry one was dropped before it reached here.
    evidence: list[str]
    source: str | None = None
    #: The page a reader can check this against.
    verify_on: str | None = None


class LineRecommendation(BaseModel):
    """One branch x SKU line: its own figures, its own sentence.

    The computed fields come from `line_recommendations` and are the same
    whoever wrote the prose; `written_by_model` says whether the prose came
    from the model or a template, because a reader deserves to know which.
    """

    scope_key: str
    branch: str
    sku: str
    #: critical | high | medium | cannot_recommend. Computed, never model-chosen.
    urgency: str
    #: Why that band, in the application's own words.
    urgency_reason: str
    headline: str
    explanation: str | None = None
    next_step: str | None = None
    evidence: list[str] = Field(default_factory=list)
    written_by_model: bool = False

    forecast_period: str | None = None
    service_level: int | None = None
    point_forecast: float | None = None
    quantile_forecast: float | None = None
    usable_stock: float | None = None
    on_order: float | None = None
    backorders: float | None = None
    days_of_cover: float | None = None
    lead_time_days: float | None = None
    protection_period_days: float | None = None
    order_up_to_level: float | None = None
    recommended_order: float | None = None
    model: str | None = None
    demand_segment: str | None = None
    #: Despatch fell short of the order here, so ordered quantity is a lower
    #: bound on real demand. Never collapsed into the forecast.
    is_censored: bool = False
    target_source: str | None = None
    #: Set when no recommendation could be produced. Not a zero.
    unavailable_reason: str | None = None
    exceptions: list[dict[str, Any]] = Field(default_factory=list)


class Recommendations(BaseModel):
    items: list[Recommendation]
    #: Per branch x SKU, ranked by the application before any model saw them.
    lines: list[LineRecommendation] = Field(default_factory=list)
    #: `openai` | `deterministic_no_key` | `deterministic_after_provider_error`
    #: | `no_lines`. Separate from `answered_by`: the two passes fail
    #: independently, so one can be model-written while the other is not.
    lines_answered_by: str | None = None
    #: How many lines fell in each urgency band across the whole workspace,
    #: so a trimmed list can say what it is not showing.
    line_counts: dict[str, int] = Field(default_factory=dict)
    lines_total: int = 0
    lines_shown: int = 0
    #: Whether this pass was served from the completed-pass cache, and how old
    #: it is. Only a fully model-written pass is cached, so a provider blip is
    #: never pinned in place.
    cached: bool = False
    cache_age_seconds: int = 0
    #: `openai` | `deterministic_no_key` | `deterministic_after_provider_error`.
    #: Surfaced so the UI can say which wrote the list.
    answered_by: str
    sources: list[str]
    facts: dict[str, Any]
    caveats: list[str]
    temperature: float
    model: str | None = None
    #: Exception type only, never the provider's message.
    provider_error: str | None = None


@router.get("/status", summary="Whether the assistant is configured, and how to configure it")
def status() -> dict[str, Any]:
    return llm.setup_instructions() | {"suggested_questions": list(service.SUGGESTED_QUESTIONS)}


@router.post("/ask", response_model=AssistantAnswer, summary="Ask a question about this application's data")
def ask(payload: AssistantQuestion, db: Session = Depends(get_db)) -> Any:
    return service.ask(
        db,
        payload.question,
        [turn.model_dump() for turn in payload.history],
        payload.current_scope,
    )


@router.get(
    "/recommendations",
    response_model=Recommendations,
    summary="What this application thinks is worth attention, explained",
)
def get_recommendations(
    prose: bool = Query(
        True,
        description=(
            "False skips both model calls and returns the computed payload - "
            "the ranking, every figure and each line's own reason - in about "
            "six seconds instead of thirty-five. Nothing in it is less "
            "accurate; only the wording is templated, and `answered_by` says "
            "`computed_only`."
        ),
    ),
    db: Session = Depends(get_db),
) -> Any:
    """A standing recommendation pass over the same bounded read-only tools.

    `prose` is the only parameter and it cannot steer which evidence is
    gathered - the same five tools run every time, in the same order. It
    chooses whether a model writes the wording over facts that were computed
    either way (D-104).
    """
    return recommendations.generate(db, prose=prose)
