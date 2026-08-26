"""Stable platform error envelope and request-id plumbing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


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
    details = {"fields": [str(item.get("loc", ())) for item in errors]}
    csrf_error = any(
        tuple(item.get("loc", ()))[:1] == ("header",)
        and "csrf" in str(item.get("loc", ())).lower()
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


def uuid_string(value: UUID | str) -> str:
    return str(value)
