"""Stable platform error envelope and request-id plumbing."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import exc as sa_exc


class Error(BaseModel):
    """Frozen public error envelope used by every platform route."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: UUID


@dataclass
class PlatformError(Exception):
    """An error safe to expose through the public platform envelope."""

    code: str
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)


def is_transient_infrastructure_error(exc: BaseException) -> bool:
    """True for failures that a retry can plausibly fix (not server bugs).

    Network/timeout errors talking to providers and lost or exhausted
    database connections stay ``provider_unavailable`` (503, retryable);
    anything else reaching the global handler is an ``internal_error``.
    """

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, (sa_exc.TimeoutError, sa_exc.DisconnectionError)):
        return True
    if isinstance(exc, sa_exc.DBAPIError) and exc.connection_invalidated:
        return True
    if isinstance(exc, sa_exc.OperationalError):
        # psycopg maps connection loss, deadlocks, serialization failures and
        # admin shutdowns to OperationalError; schema/SQL bugs are
        # ProgrammingError and therefore stay internal_error.  sqlite3 also
        # reports "no such table" as OperationalError, so on SQLite only a
        # busy/locked database counts as transient.
        if isinstance(exc.orig, sqlite3.Error):
            text = str(exc.orig).lower()
            return "locked" in text or "busy" in text
        return True
    return False


def request_id_for(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else str(uuid4())


def error_body(request: Request, error: PlatformError) -> dict[str, Any]:
    return {
        "code": error.code,
        "message": error.message,
        "details": error.details,
        "request_id": request_id_for(request),
    }


async def platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc),
        headers={"X-Request-ID": request_id_for(request)},
    )


async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # Pydantic's detailed errors may contain field internals but no secrets;
    # flatten them into a stable platform code while retaining useful fields.
    errors = exc.errors()
    details = {
        "fields": [str(item.get("loc", ())) for item in errors],
        # Path and error type only (never the input), so a form can say which
        # field is wrong and why.
        "errors": [
            {
                "field": ".".join(
                    str(part) for part in tuple(item.get("loc", ()))[1:] if part != "__root__"
                ),
                "type": str(item.get("type", "")),
            }
            for item in errors
        ],
    }
    csrf_error = any(
        tuple(item.get("loc", ()))[:1] == ("header",) and "csrf" in str(item.get("loc", ())).lower()
        for item in errors
    )
    error = (
        PlatformError("csrf_failed", "The CSRF check failed.", 403, {})
        if csrf_error
        else PlatformError("malformed_request", "The request is not valid.", 400, details)
    )
    return JSONResponse(
        status_code=error.status_code,
        content=error_body(request, error),
        headers={"X-Request-ID": request_id_for(request)},
    )


def not_found(message: str = "The requested resource was not found.") -> PlatformError:
    return PlatformError("not_found", message, 404)


def unauthenticated(message: str = "Authentication is required.") -> PlatformError:
    return PlatformError("unauthenticated", message, 401)


def forbidden(message: str = "You do not have permission for this operation.") -> PlatformError:
    return PlatformError("forbidden", message, 403)


def csrf_failed() -> PlatformError:
    return PlatformError("csrf_failed", "The CSRF check failed.", 403)


def invalid_request(message: str, details: dict[str, Any] | None = None) -> PlatformError:
    return PlatformError("malformed_request", message, 400, details or {})


def conflict(code: str, message: str, details: dict[str, Any] | None = None) -> PlatformError:
    return PlatformError(code, message, 409, details or {})


def unprocessable(code: str, message: str, details: dict[str, Any] | None = None) -> PlatformError:
    """Return a stable business-validation error with HTTP 422 semantics."""

    return PlatformError(code, message, 422, details or {})


def stale_revision(current_revision: int | None = None) -> PlatformError:
    details = {"current_revision": current_revision} if current_revision is not None else {}
    return conflict("stale_revision", "The draft revision is stale.", details)


def version_immutable() -> PlatformError:
    return conflict("version_immutable", "Published and superseded versions are immutable.")


def invalid_state(message: str = "The requested state transition is not valid.") -> PlatformError:
    return conflict("invalid_state", message)


def idempotency_conflict() -> PlatformError:
    return conflict("idempotency_conflict", "The idempotency key was used for a different request.")


def publish_blockers(blockers: list[str]) -> PlatformError:
    """Expose the first frozen publish blocker as the primary 422 code."""

    if not blockers:
        raise ValueError("publish_blockers requires at least one blocker")
    return unprocessable(
        blockers[0],
        "The draft cannot be published.",
        {"publish_blockers": blockers},
    )


def validation_failure(
    message: str,
    details: dict[str, Any] | None = None,
    *,
    code: str = "file_operation_failed",
) -> PlatformError:
    """Return a business-validation failure using a frozen domain code.

    ``malformed_request`` is reserved for malformed wire input (HTTP 400).
    Route-level validation must identify the stable domain reason instead of
    reusing that transport error at HTTP 422.
    """

    return PlatformError(code, message, 422, details or {})
