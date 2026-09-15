"""Per-model training events, in the shape the race consumes.

The existing progress stream carries run-level counters — how many fits are
done, how many refused. That cannot drive a race, because a race needs to know
how each *model* is scoring, not how much work is left.

This turns the per-model aggregate into the four-event contract the client
already speaks:

    started   one per model, when the run first reports it
    progress  a model's score changed; `epoch` is scopes scored so far
    finished  the run reached a terminal state
    failed    the model produced no score at all and did raise

`epoch` is scopes-scored rather than a gradient-descent epoch, because that is
what actually advances here: a model is fitted once per scope, and its running
median is the thing that moves. Calling it `epoch` keeps one vocabulary on the
wire.

**A model with failures is not a failed model.** A model can raise on two
scopes and score on forty; freezing its bar would be wrong. `failed` is emitted
only when a model finished with nothing scored *and* at least one raise — it
never produced a number, so it has no position in the race.
"""

from __future__ import annotations

from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.models.training import TrainingRun
from app.services.training import monitor as monitor_service

#: Below this change in accuracy a model has not meaningfully moved, and an
#: event would only add traffic. The client eases between values anyway.
MIN_DELTA = 0.05


def _accuracy(model: dict[str, Any]) -> float | None:
    """100 - median MAPE, clamped at zero — the project's own definition."""
    mape = model.get("median_mape")
    if mape is None or not model.get("scored"):
        return None
    return max(0.0, 100.0 - float(mape))


def diff(
    previous: dict[str, tuple[int, float]],
    models: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[int, float]]]:
    """Events implied by the move from `previous` to `models`."""
    events: list[dict[str, Any]] = []
    state: dict[str, tuple[int, float]] = {}

    for model in models:
        model_id = model["model_id"]
        accuracy = _accuracy(model)
        scored = int(model.get("scored") or 0)

        if model_id not in previous:
            events.append(
                {
                    "type": "started",
                    "modelId": model_id,
                    "totalEpochs": int(model.get("total") or 0),
                }
            )

        if accuracy is None:
            state[model_id] = previous.get(model_id, (0, -1.0))
            continue

        seen_epoch, seen_value = previous.get(model_id, (-1, -1.0))
        if scored != seen_epoch or abs(accuracy - seen_value) >= MIN_DELTA:
            events.append(
                {
                    "type": "progress",
                    "modelId": model_id,
                    "epoch": scored,
                    "value": round(accuracy, 3),
                }
            )
            state[model_id] = (scored, accuracy)
        else:
            state[model_id] = (seen_epoch, seen_value)

    return events, state


def terminal_events(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`finished` or `failed`, once per model, when the run is over."""
    out: list[dict[str, Any]] = []
    for model in models:
        accuracy = _accuracy(model)
        if accuracy is None:
            if int(model.get("failed") or 0) > 0:
                out.append(
                    {
                        "type": "failed",
                        "modelId": model["model_id"],
                        "error": "Every fit for this model raised; it produced no score.",
                    }
                )
            # A model that is merely Ineligible everywhere is not Failed. It
            # gets no terminal event and stays at "not scored" — a different
            # fact, and one this project refuses to collapse.
            continue
        out.append(
            {
                "type": "finished",
                "modelId": model["model_id"],
                "metrics": {
                    "accuracy": round(accuracy, 3),
                    "wins": int(model.get("champion_count") or 0),
                    "medianWape": model.get("median_wape"),
                },
            }
        )
    return out


def snapshot_events(db: Session, run: TrainingRun) -> Iterator[dict[str, Any]]:
    """Every event needed to render a finished run from cold.

    A client arriving after a run ended still needs a full field, so the whole
    state is replayed as started + progress + terminal rather than left blank.
    """
    models = monitor_service.model_progress(db, run.id)
    events, _ = diff({}, models)
    yield from events
    if run.status not in ("running", "queued", "pending"):
        yield from terminal_events(models)
