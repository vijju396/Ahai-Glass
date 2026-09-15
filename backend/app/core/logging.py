"""Structured JSON logging with a per-request correlation ID.

One line per event, machine-parseable, no stack traces or file paths in
anything that reaches a client (docs/ARCHITECTURE.md SS8). The correlation ID
travels from the request through the service layer into the job runner, so a
training job's logs can be tied back to the request that submitted it.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

#: Set once `configure_logging` has run. Alembic's `env.py` reads it to decide
#: whether it may reconfigure logging - see `logging_is_configured`.
_configured = False

_RESERVED = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(value: str | None) -> str:
    resolved = value or new_correlation_id()
    _correlation_id.set(resolved)
    return resolved


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # Kept in the server log only - never serialized to a client.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def logging_is_configured() -> bool:
    """Whether the application has already taken ownership of logging.

    Only `alembic/env.py` asks. When the app is running, Alembic is being
    driven in-process by `ensure_schema()`, and its `fileConfig` call would
    tear down the configuration the app just installed - including uvicorn's
    own error logger, which is how a bind failure reaches the operator.
    """
    return _configured


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler as the only root handler.

    Clearing the root handlers is deliberate: one format on one stream, so the
    output is parseable. It does **not** touch uvicorn's loggers - those carry
    their own handler on the `uvicorn` logger with `propagate = False`, and
    they keep working. What used to silence them was Alembic, not this
    function (docs/DECISIONS.md D-047).
    """
    global _configured
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "urllib3", "matplotlib", "git"):
        logging.getLogger(noisy).setLevel("WARNING")
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
