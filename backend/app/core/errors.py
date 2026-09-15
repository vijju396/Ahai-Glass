"""Consistent, stable error contract.

Every failure reaching a client is the same shape with a stable machine code.
Stack traces, file paths, SQL and connection strings never leave the server
(docs/API_CONTRACT.md SS2).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for every error with a stable client-facing code."""

    code = "internal_error"
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        remediation: str | None = None,
    ) -> None:
        self.message = message or self.message
        self.details = details or {}
        self.remediation = remediation
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND
    message = "The requested resource does not exist."


class ValidationFailedError(AppError):
    code = "validation_failed"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "The request failed validation."


class ConflictError(AppError):
    code = "conflict"
    http_status = status.HTTP_409_CONFLICT
    message = "The request conflicts with the current state."


class SourceControlFailedError(AppError):
    """A structural control from docs/VALIDATION_REPORT.md SS1 did not hold.

    Deliberately fatal: ingestion must not continue silently past a row-count
    or key-universe mismatch (data rule: "Do not continue silently if these
    controls fail").
    """

    code = "source_control_failed"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "One or more source-data controls did not hold."


class DataUnavailableError(AppError):
    code = "data_unavailable"
    http_status = status.HTTP_409_CONFLICT
    message = "The required prepared data is not available yet."


class ModelIneligibleError(AppError):
    """A validated data requirement is unmet. Never reported as a failure."""

    code = "model_ineligible"
    http_status = status.HTTP_409_CONFLICT
    message = "The model is not eligible for this series."


def _body(error: AppError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    }
    if error.remediation:
        payload["error"]["remediation"] = error.remediation
    correlation_id = get_correlation_id()
    if correlation_id:
        payload["error"]["correlation_id"] = correlation_id
    return payload


def _serialisable_fields(errors: Any) -> list[dict[str, Any]]:
    """Pydantic's `ctx` carries the raw exception a custom validator raised.

    A `ValueError` is not JSON serialisable, so passing `exc.errors()` through
    untouched turns every 422 on a schema with a custom validator into a 500 -
    the opposite of a consistent error contract. The message is what the client
    needs; the object is not.
    """
    cleaned: list[dict[str, Any]] = []
    for entry in errors:
        item = {
            key: value for key, value in dict(entry).items() if key not in {"ctx", "url"}
        }
        item["loc"] = [str(part) for part in entry.get("loc", ())]
        ctx = entry.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {key: str(value) for key, value in ctx.items()}
        cleaned.append(item)
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "handled_app_error", extra={"code": exc.code, "details": exc.details}
        )
        return JSONResponse(status_code=exc.http_status, content=_body(exc))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = ValidationFailedError(
            "The request body or query parameters are invalid.",
            details={"fields": _serialisable_fields(exc.errors())},
        )
        return JSONResponse(status_code=error.http_status, content=_body(error))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        mapped = {
            404: ("not_found", "The requested resource does not exist."),
            405: ("method_not_allowed", "That method is not allowed here."),
        }
        code, message = mapped.get(
            exc.status_code, ("http_error", str(exc.detail or "Request failed."))
        )
        error = AppError(message)
        error.code = code
        error.http_status = exc.status_code
        return JSONResponse(status_code=exc.status_code, content=_body(error))

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # Full detail to the server log; a stable, opaque code to the client.
        logger.exception("unhandled_error", extra={"exc_type": type(exc).__name__})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(AppError()),
        )
