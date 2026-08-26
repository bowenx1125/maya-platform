"""FastAPI composition root for the Wave 0 and Wave 1A vertical slice."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import (
    PlatformError,
    error_body,
    platform_error_handler,
    request_id_for,
    request_validation_handler,
)
from app.modules.agents.router import router as agents_router
from app.modules.auth.router import router as auth_router
from app.modules.avatars.router import router as avatars_router
from app.modules.knowledge.recovery import recover_startup
from app.modules.knowledge.router import router as knowledge_router
from app.modules.org.router import router as org_router
from app.modules.voices.router import router as voices_router
from app.modules.voices.service import startup_voice_cleanup
from app.seed import seed_demo_data

logger = logging.getLogger("maya.backend")


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    initialize_database: bool = True,
) -> FastAPI:
    """Build an isolated application instance.

    Tests pass their own Settings/Database, while production uses the cached
    environment configuration and the configured SQLite file.
    """

    runtime_settings = settings or get_settings()
    runtime_database = database or Database(
        runtime_settings.database_url,
        runtime_settings.resolved_data_root,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime_settings.validate_runtime()
        runtime_settings.ensure_data_root()
        if initialize_database:
            if runtime_settings.is_test:
                runtime_database.initialize_schema()
            else:
                runtime_database.upgrade_schema()
            with runtime_database.session() as session:
                recover_startup(session, runtime_settings.resolved_data_root)
                startup_voice_cleanup(runtime_settings.resolved_data_root)
                seed_demo_data(session)
        yield
        runtime_database.dispose()

    app = FastAPI(
        title="Maya Teaching Platform API",
        version="0.1.0-g0.4",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.database = runtime_database
    if settings is not None:
        # Route dependencies use get_settings; keep injected app instances
        # internally consistent without changing global process settings.
        app.dependency_overrides[get_settings] = lambda: runtime_settings

    app.add_exception_handler(PlatformError, platform_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type]

    async def framework_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        status_code = exc.status_code
        if status_code == 404:
            code, message = "not_found", "The requested resource was not found."
        elif status_code == 401:
            code, message = "unauthenticated", "Authentication is required."
        elif status_code == 403:
            code, message = "forbidden", "You do not have permission for this operation."
        else:
            code, message = "malformed_request", "The request could not be completed."
        error = PlatformError(code, message, status_code)
        return JSONResponse(
            status_code=status_code,
            content=error_body(request, error),
            headers={"X-Request-ID": request_id_for(request)},
        )

    app.add_exception_handler(StarletteHTTPException, framework_error_handler)  # type: ignore[arg-type]

    async def unhandled_error_handler(request: Request, _exc: Exception) -> JSONResponse:
        # Keep response text and details frozen/safe.  Log only the exception
        # type and request ID; exception messages can contain provider data or
        # user input and therefore must not be copied to logs or the envelope.
        request_id = request_id_for(request)
        logger.error(
            "Unhandled request failure request_id=%s error_type=%s",
            request_id,
            type(_exc).__name__,
            exc_info=False,
        )
        error = PlatformError(
            "provider_unavailable",
            "The service is temporarily unavailable.",
            503,
        )
        return JSONResponse(
            status_code=503,
            content=error_body(request, error),
            headers={"X-Request-ID": request_id},
        )

    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.get("/health/live", tags=["Health"])
    def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    def health_ready() -> JSONResponse:
        ready = runtime_database.check_ready()
        body = {"status": "ready" if ready else "not_ready"}
        return JSONResponse(status_code=200 if ready else 503, content=body)

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(org_router, prefix="/api/v1")
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(knowledge_router, prefix="/api/v1")
    app.include_router(avatars_router, prefix="/api/v1")
    app.include_router(voices_router, prefix="/api/v1")

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            description=(
                "Demo v0.1 platform contract. Provider names, model names, "
                "external voice IDs, API keys, absolute storage paths, and "
                "prepared turn text are never public fields."
            ),
        )

        def freeze_nullable_scalars(value: Any) -> None:
            """Render Pydantic nullable scalar unions in frozen contract form."""

            if isinstance(value, dict):
                union = value.get("anyOf")
                if (
                    isinstance(union, list)
                    and len(union) == 2
                    and {branch.get("type") for branch in union if isinstance(branch, dict)}
                    == {"string", "null"}
                    and all(
                        not isinstance(branch, dict) or "format" not in branch
                        for branch in union
                    )
                ):
                    value.pop("anyOf", None)
                    value["type"] = ["string", "null"]
                for child in value.values():
                    freeze_nullable_scalars(child)
            elif isinstance(value, list):
                for child in value:
                    freeze_nullable_scalars(child)

        freeze_nullable_scalars(schema)
        # API validation errors are mapped to the frozen 400 envelope (and
        # missing CSRF headers to 403), so do not advertise FastAPI's default
        # uncontracted 422 response.
        contract_paths: dict[str, Any] = {}
        for path, path_item in schema.get("paths", {}).items():
            is_api_path = path.startswith("/api/v1/")
            if is_api_path:
                for operation in path_item.values():
                    if isinstance(operation, dict):
                        # FastAPI's generic 422 is not part of the Wave 0
                        # contract.  Wave 1A explicitly declares six frozen
                        # business-validation 422 responses and they must
                        # remain visible to the semantic comparator.
                        operation_id = operation.get("operationId")
                        if operation_id not in {
                            "uploadKnowledgeDocument",
                            "updateAgentDraft",
                            "setAgentVersionDocuments",
                            "uploadAgentMd",
                            "testAgentDraft",
                            "publishAgentVersion",
                            "enrollVoice",
                        }:
                            operation.get("responses", {}).pop("422", None)
                contract_path = path[len("/api/v1") :]
            else:
                contract_path = path
            contract_paths[contract_path] = path_item
        schema["paths"] = contract_paths
        schema["servers"] = [{"url": "/api/v1"}]
        schema["security"] = [{"sessionCookie": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
