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

from fastapi import APIRouter, Depends
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


class Recommendations(BaseModel):
    items: list[Recommendation]
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
def get_recommendations(db: Session = Depends(get_db)) -> Any:
    """A standing recommendation pass over the same bounded read-only tools.

    A GET with no parameters: it is one question, always the same one, so a
    caller cannot steer which evidence gets gathered.
    """
    return recommendations.generate(db)
