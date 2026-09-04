"""FastAPI composition root for the Wave 0 and Wave 1A vertical slice."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
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
from app.core.logging import configure_application_logging
from app.core.models import Course
from app.modules.agents.router import router as agents_router
from app.modules.auth.dependencies import get_db
from app.modules.auth.router import router as auth_router
from app.modules.auth.service import bootstrap_demo_accounts
from app.modules.avatars.router import router as avatars_router
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.events import DebateEventHub
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.prewarm import PrewarmScheduler
from app.modules.debates.playback.router import router as debate_playback_router
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlEventStore, SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
from app.modules.debates.playback.wave3_bridge import Wave3EventPublisher
from app.modules.debates.playback.wave3_projection import wave3_snapshot_projection
from app.modules.debates.setup.router import router as debate_setup_router
from app.modules.demo_acceptance.router import router as demo_acceptance_router
from app.modules.demo_baseline.router import router as demo_baseline_router
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.interactions.router import router as interaction_router
from app.modules.interactions.service import InteractionService
from app.modules.knowledge.providers import recover_embedding_provider_startup
from app.modules.knowledge.recovery import recover_startup
from app.modules.knowledge.router import router as knowledge_router
from app.modules.org.router import router as org_router
from app.modules.provider_disclosure.router import (
    get_provider_disclosure_service,
)
from app.modules.provider_disclosure.router import (
    router as provider_disclosure_router,
)
from app.modules.provider_disclosure.service import (
    ProviderDisclosureService,
    SqlAlchemyProviderDisclosureStore,
)
from app.modules.reports.real_provider import RealReportProvider
from app.modules.reports.router import router as reports_router
from app.modules.reports.service import (
    RealReportRuntime,
    ReportInsightEnqueuer,
    recover_report_jobs,
)
from app.modules.reports.task_manager import ReportTaskManager
from app.modules.voices.router import router as voices_router
from app.modules.voices.service import startup_voice_cleanup
from app.providers.control_repository import ProviderRepository
from app.providers.factory import tts_provider
from app.providers.llm_adapter import DashScopeLLMConfig
from app.providers.llm_price_card import LLMPriceCardV1
from app.providers.llm_recovery import recover_llm_startup
from app.providers.llm_tokenizer import ConservativeLLMTokenizer
from app.providers.policy_store import ensure_reviewed_policies
from app.seed import COURSE_ID, seed_demo_data

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

    configure_application_logging()
    runtime_settings = settings or get_settings()
    runtime_database = database or Database(
        runtime_settings.database_url,
        runtime_settings.resolved_data_root,
    )
    playback_tasks = TaskManager()
    playback_repository = SqlPlaybackRepository(session_factory=runtime_database.session_factory)
    selected_tts = tts_provider(runtime_settings)
    report_runtime: RealReportRuntime | None = None
    if runtime_settings.report_provider == "dashscope":
        report_policy_hash = runtime_settings.report_policy_hash or ""
        try:
            report_price_card = LLMPriceCardV1(
                version=runtime_settings.llm_price_card_version or "",
                input_price_per_million=runtime_settings.llm_input_price_cny_per_million or "0",
                cached_input_price_per_million=(
                    runtime_settings.llm_cached_input_price_cny_per_million or "0"
                ),
                output_price_per_million=runtime_settings.llm_output_price_cny_per_million or "0",
                retrieved_at=runtime_settings.llm_price_card_retrieved_at or "",
                source_content_sha256=runtime_settings.llm_price_card_source_content_sha256
                or "0" * 64,
            )
        except Exception:
            # Runtime validation reports the safe configuration error during
            # lifespan; keep composition construction side-effect free.
            report_price_card = LLMPriceCardV1()
        report_runtime = RealReportRuntime(
            provider=RealReportProvider(
                config=DashScopeLLMConfig(
                    api_key=runtime_settings.dashscope_api_key or "",
                    workspace_id=runtime_settings.dashscope_workspace_id or "unconfigured",
                    region=runtime_settings.dashscope_region or "cn-beijing",
                    policy_hash=report_policy_hash,
                ),
                tokenizer=ConservativeLLMTokenizer(),
                price_card=report_price_card,
                policy_hash=report_policy_hash,
            ),
            repository=ProviderRepository(runtime_database, require_export_confirmation=False),
        )
    event_hub = DebateEventHub(SqlEventStore(runtime_database.session_factory))
    wave3_events = Wave3EventPublisher(runtime_database.session_factory, event_hub)
    report_tasks = ReportTaskManager(
        runtime_database.session_factory,
        wave3_events.publish_summary,
        real_runtime=report_runtime,
    )
    playback_service = PlaybackService(
        playback_repository,
        audio_store=AudioStore(
            runtime_settings.resolved_data_root,
            tts_provider=selected_tts,
        ),
        event_hub=event_hub,
        task_manager=playback_tasks,
        turn_preparer=SqlTurnPreparer(settings=runtime_settings),
        tts_provider=selected_tts,
        session_factory=runtime_database.session_factory,
        settings=runtime_settings,
        snapshot_projector=wave3_snapshot_projection,
    )

    def _prewarm_plan(debate_id: str) -> list[tuple[str, bool]]:
        """This Debate's turns in order, and whether each is already made."""

        with runtime_database.session() as session:
            debate = playback_repository.get_debate(session, debate_id)
            if debate is None or str(getattr(debate, "status", "")) != "draft":
                return []
            # A draft that cannot be started must not be warmed: every turn
            # would be a real provider call spent on a lesson the teacher will
            # be told to fix before it can run.
            from app.modules.debates.topic_language import validate_english_topic

            try:
                validate_english_topic(str(getattr(debate, "topic", "")))
            except Exception:
                return []
            turns = playback_repository.turns(session, debate)
            if not turns:
                # A draft has no plan until something asks for one. Warming is
                # the only asker before Start, and Start stops warming before
                # it runs, so the two never write this at the same time.
                ensure = getattr(playback_repository, "ensure_turn_plan", None)
                if callable(ensure):
                    turns = ensure(session, debate)
                    session.commit()
            return [
                (
                    str(getattr(turn, "id", "")),
                    str(getattr(turn, "generation_status", ""))
                    in {"final_ready", "ready", "completed"},
                )
                for turn in sorted(turns, key=lambda item: int(getattr(item, "turn_index", 0) or 0))
            ]

    async def _prewarm_prepare(debate_id: str, turn_id: str) -> None:
        with runtime_database.session() as session:
            await playback_service.prepare_turn(session, debate_id, turn_id)
            session.commit()

    prewarm = PrewarmScheduler(plan=_prewarm_plan, prepare=_prewarm_prepare)
    if runtime_settings.is_test:
        # Warming is a runtime behaviour, not part of any request's contract.
        # Left armed under a test client it writes turns between a test's own
        # statements, which is a race no assertion can be written against. The
        # scheduler's own rules are tested by driving it directly.
        prewarm.disable()

    def publish_interaction_event(event: Any) -> None:
        wave3_events.publish_interaction(event)
        if event.event_type == "interaction.closed":
            report_tasks.wake(str(event.debate_id))

    interaction_service = InteractionService(
        session_factory=runtime_database.session_factory,
        settings=runtime_settings,
        event_publisher=publish_interaction_event,
        insight_enqueuer=ReportInsightEnqueuer(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        wave3_events.bind_running_loop()
        report_tasks.bind_running_loop()
        prewarm.bind_running_loop()
        runtime_settings.validate_runtime()
        runtime_settings.ensure_data_root()
        if initialize_database:
            if runtime_settings.is_test:
                runtime_database.initialize_schema()
            else:
                runtime_database.upgrade_schema()
            if runtime_settings.demo_mode:
                # Parse first, then seed a fresh organization and apply the
                # complete private-account desired graph in one BEGIN
                # IMMEDIATE transaction.  Once a catalog has renamed or
                # disabled identities, skip the historical strict seed and
                # let the durable account binding remain authoritative.
                def seed_if_empty(session: Any) -> None:
                    if session.scalar(select(Course.id).where(Course.id == COURSE_ID)) is None:
                        seed_demo_data(session)

                bootstrap_demo_accounts(
                    runtime_database,
                    runtime_settings,
                    seed_if_empty,
                )
            else:
                with runtime_database.session() as session:
                    if session.scalar(select(Course.id).where(Course.id == COURSE_ID)) is None:
                        seed_demo_data(session)
            if not runtime_settings.is_test:
                with runtime_database.session() as session:
                    ensure_demo_baseline(session, runtime_settings.resolved_data_root)
                # A reviewed provider policy is operator evidence, not runtime
                # state. Reinstalling it here is what keeps "reset the runtime"
                # from also meaning "real providers stop working".
                with runtime_database.session() as session:
                    restored = ensure_reviewed_policies(
                        session, runtime_settings.resolved_config_root
                    )
                    if restored:
                        session.commit()
                        logger.info("Reinstalled %s reviewed provider policies", restored)
            recover_embedding_provider_startup(runtime_database)
            recover_llm_startup(ProviderRepository(runtime_database))
            with runtime_database.session() as session:
                recover_startup(session, runtime_settings.resolved_data_root)
                startup_voice_cleanup(runtime_settings.resolved_data_root)
                await playback_service.recover_startup(session)
                recover_report_jobs(session)
            report_tasks.schedule_pending()
        try:
            yield
        finally:
            await prewarm.close()
            await report_tasks.close()
            await playback_tasks.close()
            runtime_database.dispose()

    app = FastAPI(
        title="Maya Teaching Platform API",
        version="0.1.0-g0.8-wave3",
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.state.database = runtime_database
    app.state.playback_service = playback_service
    app.state.interaction_service = interaction_service
    app.state.interaction_event_publisher = publish_interaction_event
    app.state.insight_enqueuer = interaction_service.insight_enqueuer
    app.state.wave3_event_publisher = wave3_events
    app.state.prewarm_scheduler = prewarm
    app.state.report_task_manager = report_tasks
    app.state.report_runtime = report_runtime
    if settings is not None:
        # Route dependencies use get_settings; keep injected app instances
        # internally consistent without changing global process settings.
        app.dependency_overrides[get_settings] = lambda: runtime_settings

    def request_provider_disclosure_service(
        db: Session = Depends(get_db),
    ) -> ProviderDisclosureService:
        return ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))

    app.dependency_overrides[get_provider_disclosure_service] = request_provider_disclosure_service

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
        path = request.url.path
        teacher_interaction_path = path.startswith("/api/v1/debates/") and path.endswith(
            ("/interaction", "/interaction/open", "/interaction/close")
        )
        if path.startswith("/api/v1/classroom-interactions/") or teacher_interaction_path:
            # Public classroom capabilities must never be cached or leaked by
            # a referrer, including PlatformError/validation responses that
            # replace the route's injected Response object.
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
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
    app.include_router(debate_setup_router, prefix="/api/v1")
    app.include_router(debate_playback_router, prefix="/api/v1")
    app.include_router(interaction_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(provider_disclosure_router, prefix="/api/v1")
    app.include_router(demo_baseline_router, prefix="/api/v1")
    app.include_router(demo_acceptance_router, prefix="/api/v1")

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
            description=(
                "Demo v0.1 platform contract. Supplier identity appears only in the "
                "teacher-only ProviderDataCallV1 disclosure. Model names, external "
                "resource IDs, API keys, absolute storage paths, and prepared turn "
                "text are never public fields."
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
                        not isinstance(branch, dict) or "format" not in branch for branch in union
                    )
                ):
                    string_branch = next(
                        (
                            branch
                            for branch in union
                            if isinstance(branch, dict) and branch.get("type") == "string"
                        ),
                        None,
                    )
                    value.pop("anyOf", None)
                    value["type"] = ["string", "null"]
                    if isinstance(string_branch, dict) and isinstance(
                        string_branch.get("enum"), list
                    ):
                        value["enum"] = [*string_branch["enum"], None]
                for child in value.values():
                    freeze_nullable_scalars(child)
            elif isinstance(value, list):
                for child in value:
                    freeze_nullable_scalars(child)

        freeze_nullable_scalars(schema)
        component_schemas = schema.get("components", {}).get("schemas", {})
        participant_schema = component_schemas.get("DebateParticipant", {})
        participant_properties = participant_schema.get("properties", {})
        if "effective_voice_profile_id" in participant_properties:
            participant_properties["effective_voice_profile_id"] = {
                "oneOf": [
                    {"type": "string", "format": "uuid"},
                    {"type": "null"},
                ]
            }
        turn_schema = component_schemas.get("DebateTurn", {})
        turn_properties = turn_schema.get("properties", {})
        if "playback_resource" in turn_properties:
            turn_properties["playback_resource"] = {
                "oneOf": [
                    {"$ref": "#/components/schemas/DebatePlaybackResource"},
                    {"type": "null"},
                ]
            }
        for name, component in component_schemas.items():
            if not name.endswith("RetrievalSource") or not isinstance(component, dict):
                continue
            properties = component.get("properties", {})
            if "chunk_id" in properties:
                properties["chunk_id"] = {"type": "string", "format": "uuid"}
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
                        # contract.  Only operations with an explicit frozen
                        # business-validation 422 keep that response in the
                        # generated server contract.
                        operation_id = operation.get("operationId")
                        if operation_id == "streamRetainedTurnAudio":
                            for parameter in operation.get("parameters", []):
                                if not isinstance(parameter, dict):
                                    continue
                                if parameter.get("name") == "Range":
                                    parameter["schema"] = {
                                        "type": "string",
                                        "pattern": r"^bytes=(?:[0-9]+-[0-9]*|-[0-9]+)$",
                                    }
                                elif parameter.get("name") == "If-Range":
                                    parameter["schema"] = {
                                        "oneOf": [
                                            {
                                                "type": "string",
                                                "pattern": r'^"[0-9a-f]{64}"$',
                                            },
                                            {
                                                "type": "string",
                                                "pattern": (
                                                    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
                                                    r"[0-9]{2} "
                                                    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|"
                                                    r"Aug|Sep|Oct|Nov|Dec) "
                                                    r"[0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT$"
                                                ),
                                            },
                                        ]
                                    }
                                elif parameter.get("name") == "media_ticket":
                                    parameter["schema"] = {
                                        "type": "string",
                                        "minLength": 43,
                                        "maxLength": 43,
                                        "pattern": r"^[A-Za-z0-9_-]{43}$",
                                    }
                        if operation_id not in {
                            "uploadKnowledgeDocument",
                            "updateAgentDraft",
                            "setAgentVersionDocuments",
                            "uploadAgentMd",
                            "testAgentDraft",
                            "publishAgentVersion",
                            "enrollVoice",
                            "createDebate",
                            "updateDebateDraft",
                            "startDebate",
                            "submitVote",
                            "submitBarrage",
                            "translateCurrentPublishedContent",
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
