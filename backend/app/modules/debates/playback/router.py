"""Teacher playback REST and WebSocket routes.

The composition root injects ``app.state.playback_service``.  A safe SQL
adapter fallback is provided for local startup after migration 0005, while
all route authorization still comes from the live Session and course teacher
membership on every request/command.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Iterator
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketState

from app.core.config import Settings
from app.core.errors import Error, PlatformError, forbidden, not_found
from app.core.origin import origin_allowed, origin_tuple
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext, get_auth_context, session_hash
from app.modules.debates.schemas import (
    AdvancePlaybackRequest,
    DebateDetail,
    DebateStartRequest,
    FinishDebateRequest,
    PlaybackCommandRequest,
    PlaybackControlRequest,
    PlaybackState,
    RetryPreparationRequest,
    Transcript,
)
from app.modules.translations.service import attach_translated_text
from app.providers.factory import tts_provider

from .audio import AudioStore
from .eligibility import has_complete_finished_playback
from .events import DebateEventHub, private_result_to_wire
from .schemas import (
    ControllerAcquireCommand,
    EndedAckCommand,
    MediaPrepareCommand,
    PlayFailedCommand,
    PrivateResult,
    StartedAckCommand,
    WSCommand,
)
from .service import PlaybackService
from .sql_repository import SqlEventStore, SqlPlaybackRepository

router = APIRouter(tags=["Debates"])
LOGGER = logging.getLogger(__name__)


def _origin_tuple(value: str | None) -> tuple[str, str, int | None] | None:
    """Keep the playback module's parsing seam backed by the shared helper."""

    return origin_tuple(value)


def get_playback_service(request: Request) -> PlaybackService:
    existing = getattr(request.app.state, "playback_service", None)
    if isinstance(existing, PlaybackService):
        return existing
    database = getattr(request.app.state, "database", None)
    settings = getattr(request.app.state, "settings", None)
    if database is None or settings is None:
        raise RuntimeError("playback service is not configured")
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    event_hub = DebateEventHub(SqlEventStore(database.session_factory))
    selected_tts = tts_provider(settings)
    service = PlaybackService(
        repository,
        audio_store=AudioStore(settings.resolved_data_root, tts_provider=selected_tts),
        event_hub=event_hub,
        session_factory=database.session_factory,
        settings=settings,
        tts_provider=selected_tts,
    )
    request.app.state.playback_service = service
    return service


def _state_or_detail(
    service: PlaybackService,
    db: Session,
    debate_id: str,
    state: Any,
    context: AuthContext | None = None,
) -> Any:
    """Use a setup-owned detail projection when composition supplies one."""

    detail_builder = getattr(service.repository, "debate_detail", None)
    if callable(detail_builder):
        return detail_builder(db, debate_id)
    if context is not None:
        try:
            from app.modules.debates.setup.service import get_debate

            return get_debate(db, actor_user_id=context.user.id, debate_id=debate_id)
        except (ImportError, AttributeError):
            pass
    return state


def _session_hash(context: AuthContext) -> str:
    return session_hash(context.raw_session_token)


@router.post(
    "/debates/{debate_id}/start",
    operation_id="startDebate",
    response_model=DebateDetail,
    responses={
        200: {"description": "Debate started."},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
async def start_debate_route(
    debate_id: UUID,
    payload: DebateStartRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    expected_revision = payload.expected_revision
    expected_pointer = (
        str(payload.expected_current_audio_debate_id)
        if payload.expected_current_audio_debate_id is not None
        else None
    )
    confirm = payload.confirm_previous_audio_cleanup
    state = await service.start(
        db,
        str(debate_id),
        expected_revision=expected_revision,
        expected_current_audio_debate_id=expected_pointer,
        confirm_previous_audio_cleanup=confirm,
        context=context,
        idempotency_key=idempotency_key,
        request_id=getattr(request.state, "request_id", None),
    )
    return _state_or_detail(service, db, str(debate_id), state, context)


@router.post(
    "/debates/{debate_id}/preparation/retry",
    operation_id="retryDebatePreparation",
    response_model=PlaybackState,
    responses={
        200: {"description": "Provider-gated turn preparation was re-enqueued."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
async def retry_debate_preparation_route(
    debate_id: UUID,
    payload: RetryPreparationRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    return await service.retry_preparation(
        db,
        str(debate_id),
        turn_id=str(payload.turn_id),
        expected_control_version=payload.expected_control_version,
        context=context,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/debates/{debate_id}/pause",
    operation_id="pauseDebate",
    response_model=PlaybackState,
    responses={
        200: {"description": "Authoritative paused playback state."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
async def pause_debate_route(
    debate_id: UUID,
    payload: PlaybackControlRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    return await service.pause(
        db,
        str(debate_id),
        expected_control_version=payload.expected_control_version,
        context=context,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/debates/{debate_id}/resume",
    operation_id="resumeDebate",
    response_model=PlaybackState,
    responses={
        200: {"description": "Authoritative resumed playback state."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
async def resume_debate_route(
    debate_id: UUID,
    payload: PlaybackControlRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    return await service.resume(
        db,
        str(debate_id),
        expected_control_version=payload.expected_control_version,
        context=context,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/debates/{debate_id}/finish",
    operation_id="finishDebate",
    response_model=DebateDetail,
    responses={
        200: {"description": "Debate finished fully or partially."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
async def finish_debate_route(
    debate_id: UUID,
    payload: FinishDebateRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    state = await service.finish(
        db,
        str(debate_id),
        expected_control_version=payload.expected_control_version,
        expected_current_turn_id=(
            str(payload.expected_current_turn_id)
            if payload.expected_current_turn_id is not None
            else None
        ),
        context=context,
        idempotency_key=idempotency_key,
    )
    return _state_or_detail(service, db, str(debate_id), state, context)


def _control_dependencies() -> dict[str, Any]:
    return {
        "responses": {
            200: {"description": "Authoritative playback state."},
            403: {"model": Error},
            404: {"model": Error},
            409: {"model": Error},
        },
    }


@router.post(
    "/debates/{debate_id}/next",
    operation_id="advanceDebatePlayback",
    response_model=PlaybackState,
    responses={
        200: {"description": "Authoritative playback state after advancing one live turn."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
async def advance_debate_playback_route(
    debate_id: UUID,
    payload: AdvancePlaybackRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    return await service.next(
        db,
        str(debate_id),
        expected_control_version=payload.expected_control_version,
        expected_current_turn_id=str(payload.expected_current_turn_id),
        context=context,
    )


@router.post(
    "/debates/{debate_id}/replay",
    operation_id="replayDebate",
    response_model=PlaybackState,
    responses=_control_dependencies()["responses"],
)
async def replay_debate_route(
    debate_id: UUID,
    payload: PlaybackCommandRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Any:
    return await service.replay_all(
        db,
        str(debate_id),
        expected_control_version=payload.expected_control_version,
        context=context,
    )


@router.get(
    "/debates/{debate_id}/transcript",
    operation_id="getDebateTranscript",
    response_model=Transcript,
    responses={
        200: {"description": "Published turns and retained audio."},
        403: {"model": Error},
        404: {"model": Error},
    },
)
async def transcript_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Transcript:
    # A partial Finish has product status ``debate_finished`` but terminal
    # stopped playback.  Require the complete immutable plan as well as the
    # normal terminal state so partial history cannot leak through this route.
    debate = service._get_debate(db, str(debate_id))
    debate_status = str(getattr(debate, "status", ""))
    if debate_status == "stopped" or (
        debate_status in {"debate_finished", "completed"}
        and not has_complete_finished_playback(db, str(debate_id))
    ):
        raise not_found()
    snapshot, _ = await service.snapshot(db, str(debate_id), context)
    return Transcript.model_validate(
        {
            "debate_id": str(debate_id),
            "turns": attach_translated_text(
                db,
                debate_id=str(debate_id),
                turns=snapshot["public_turns"],
            ),
            "audio_retained": service.audio_retained(db, str(debate_id)),
        }
    )


def _websocket_origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    # The classroom URL is the configured gateway origin.  Do not derive an
    # allow-list from the Host header: a crafted Host/Origin pair must not
    # turn an arbitrary reverse-proxy origin into a trusted WebSocket.
    configured = getattr(settings, "gateway_origin", None) or settings.classroom_public_base_url
    if configured:
        return origin_allowed(websocket.headers.get("origin"), settings)
    # Tests intentionally leave the deployment origin unset; in that narrow
    # case accept only the exact origin represented by the test gateway.
    if not bool(getattr(settings, "is_test", False)):
        return False
    gateway_scheme = "https" if websocket.url.scheme == "wss" else "http"
    return origin_allowed(
        websocket.headers.get("origin"),
        settings,
        request_origin=f"{gateway_scheme}://{websocket.url.netloc}",
    )


@contextlib.contextmanager
def _websocket_session(database: Any, settings: Settings) -> Iterator[Session]:
    """Provide one short-lived DB session for a WebSocket operation.

    A WebSocket can outlive the HTTP request dependency scope by hours.  Do
    not bind a SQLAlchemy session to that socket: a single auth/snapshot read
    would otherwise keep a QueuePool connection checked out until disconnect.
    The event stream remains long-lived in memory, while every database
    operation gets its own transaction and promptly returns its connection.
    """

    db: Session = database.session_factory()
    db.info["maya_settings"] = settings
    try:
        yield db
        db.commit()
    except BaseException:
        with contextlib.suppress(Exception):
            db.rollback()
        raise
    finally:
        db.close()


async def _close_ws(websocket: WebSocket, code: int) -> None:
    """Close with a classification-only code and no configuration details."""

    if websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close(code=code)


@router.get(
    "/debates/{debate_id}/events",
    status_code=101,
    operation_id="connectDebateEvents",
    responses={
        101: {"description": "Switching Protocols."},
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def debate_events_contract_route(
    debate_id: UUID,
    since_sequence: int = Query(0, ge=0),
) -> Response:
    """Document the WebSocket upgrade without adding a second product API."""

    del debate_id, since_sequence
    return Response(status_code=101)


@router.websocket("/debates/{debate_id}/events")
async def debate_events_route(
    websocket: WebSocket,
    debate_id: UUID,
    since_sequence: int = Query(0, ge=0),
) -> None:
    app = websocket.app
    settings = getattr(app.state, "settings", None)
    database = getattr(app.state, "database", None)
    # ASGI turns a pre-accept ``websocket.close`` into an HTTP 403 handshake
    # rejection, so a real browser cannot observe our private 4401/4403/1011
    # classification.  Upgrade once before validation, send no application
    # data, then close immediately on failure with an empty reason.
    await websocket.accept()
    if not isinstance(settings, Settings) or database is None:
        await _close_ws(websocket, 1011)
        return
    if not _websocket_origin_allowed(websocket, settings):
        await _close_ws(websocket, 4403)
        return
    raw_token = websocket.cookies.get("maya_session")
    try:
        service = get_playback_service(websocket)  # type: ignore[arg-type]
        with _websocket_session(database, settings) as handshake_db:
            context = get_auth_context(handshake_db, settings, raw_token)
    except Exception:
        # Settings/database/service failures are server faults.  They must not
        # masquerade as an Origin mismatch, and the close frame must not echo
        # a private URL, database path, key, or token.
        LOGGER.error("WebSocket handshake failed before authorization.")
        await _close_ws(websocket, 1011)
        return
    if context is None:
        await _close_ws(websocket, 4401)
        return
    connection_id = str(uuid4())
    epoch: str | None = None
    seen_command_ids: set[str] = set()

    async def snapshot_factory() -> tuple[dict[str, Any], int]:
        with _websocket_session(database, settings) as snapshot_db:
            current = get_auth_context(snapshot_db, settings, raw_token)
            if current is None:
                raise forbidden()
            return await service.snapshot(snapshot_db, str(debate_id), current)

    stream = cast(
        AsyncGenerator[dict[str, Any], None],
        service.event_hub.stream(str(debate_id), snapshot_factory),
    )
    event_task: asyncio.Task[Any] | None = None
    receive_task: asyncio.Task[Any] | None = None
    try:
        event_task = asyncio.create_task(stream.__anext__())
        while True:
            receive_task = asyncio.create_task(websocket.receive_json())
            done, pending = await asyncio.wait(
                {event_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if event_task in pending:
                # A command arrived first; preserve the event subscription.
                pass
            elif receive_task in pending:
                receive_task.cancel()
            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    break
                # Public stream events can include the one reviewed raw-text
                # exception, ``interaction.barrage_created``.  Revalidate the
                # live session and course-teacher scope immediately before
                # every delivery so revocation or membership changes cannot
                # leave a long-lived socket authorized to receive it.
                delivery_authorized = False
                with _websocket_session(database, settings) as delivery_db:
                    fresh = get_auth_context(delivery_db, settings, raw_token)
                    if fresh is not None:
                        try:
                            await service.snapshot(delivery_db, str(debate_id), fresh)
                            delivery_authorized = True
                        except PlatformError:
                            delivery_authorized = False
                if not delivery_authorized:
                    await _close_ws(websocket, 4401)
                    break
                await websocket.send_json(event)
                event_task = asyncio.create_task(stream.__anext__())
            if receive_task in done:
                raw = receive_task.result()
                command_id = uuid4()
                try:
                    command: WSCommand = TypeAdapter(WSCommand).validate_python(raw)
                    command_id = command.command_id
                except ValidationError:
                    # Even malformed input must not get a free pass around
                    # the live-session check.  A revoked socket is closed
                    # before returning a private malformed-command result.
                    close_for_revocation = False
                    with _websocket_session(database, settings) as command_db:
                        fresh = get_auth_context(command_db, settings, raw_token)
                        if fresh is None:
                            rejected = await service.command_duplicate_or_rejected(
                                command_db,
                                str(debate_id),
                                command_id=str(command_id),
                                code="session_revoked",
                                recoverable=False,
                            )
                            close_for_revocation = True
                        else:
                            rejected = await service.command_duplicate_or_rejected(
                                command_db,
                                str(debate_id),
                                command_id=str(command_id),
                                code="malformed_command",
                                recoverable=False,
                            )
                    await websocket.send_json(private_result_to_wire(rejected))
                    if close_for_revocation:
                        await _close_ws(websocket, 4401)
                        break
                    continue
                close_for_revocation = False
                result: PrivateResult | None = None
                with _websocket_session(database, settings) as command_db:
                    fresh = get_auth_context(command_db, settings, raw_token)
                    if fresh is None:
                        result = await service.command_duplicate_or_rejected(
                            command_db,
                            str(debate_id),
                            command_id=str(command.command_id),
                            code="session_revoked",
                            recoverable=False,
                        )
                        close_for_revocation = True
                    else:
                        command_key = str(command.command_id)
                        if command_key in seen_command_ids:
                            result = await service.command_duplicate(
                                command_db,
                                str(debate_id),
                                command_id=command_key,
                            )
                        else:
                            seen_command_ids.add(command_key)
                            if str(command.debate_id) != str(debate_id):
                                result = await service.command_duplicate_or_rejected(
                                    command_db,
                                    str(debate_id),
                                    command_id=str(command.command_id),
                                    code="forbidden",
                                    recoverable=False,
                                )
                            else:
                                try:
                                    if isinstance(command, ControllerAcquireCommand):
                                        acquired = await service.controller_acquire(
                                            command_db,
                                            str(debate_id),
                                            command_id=str(command.command_id),
                                            expected_control_version=command.expected_control_version,
                                            session_hash=_session_hash(fresh),
                                            connection_id=connection_id,
                                            context=fresh,
                                        )
                                        result = acquired
                                        epoch = str(acquired.controller_epoch)
                                        service.register_connection(epoch, websocket.send_json)
                                    elif isinstance(command, MediaPrepareCommand):
                                        _media, result = await service.media_prepare(
                                            command_db,
                                            str(debate_id),
                                            command_id=str(command.command_id),
                                            expected_control_version=command.expected_control_version,
                                            epoch=str(command.controller_epoch),
                                            session_hash=_session_hash(fresh),
                                            turn_id=str(command.turn_id),
                                            action=command.playback_action,
                                            context=fresh,
                                        )
                                    elif isinstance(command, StartedAckCommand):
                                        await service.started_ack(
                                            command_db,
                                            str(debate_id),
                                            command_id=str(command.command_id),
                                            expected_control_version=command.expected_control_version,
                                            epoch=str(command.controller_epoch),
                                            session_hash=_session_hash(fresh),
                                            turn_id=str(command.turn_id),
                                            action=command.playback_action,
                                            context=fresh,
                                        )
                                    elif isinstance(command, EndedAckCommand):
                                        before = service._state(
                                            command_db,
                                            service._get_debate(command_db, str(debate_id)),
                                        ).status
                                        await service.ended_ack(
                                            command_db,
                                            str(debate_id),
                                            command_id=str(command.command_id),
                                            expected_control_version=command.expected_control_version,
                                            epoch=str(command.controller_epoch),
                                            session_hash=_session_hash(fresh),
                                            turn_id=str(command.turn_id),
                                            context=fresh,
                                        )
                                        after = service._state(
                                            command_db,
                                            service._get_debate(command_db, str(debate_id)),
                                        ).status
                                        if before != "playing" or after == before:
                                            result = await service.command_duplicate_or_rejected(
                                                command_db,
                                                str(debate_id),
                                                command_id=str(command.command_id),
                                                code="duplicate_command",
                                                recoverable=True,
                                            )
                                    elif isinstance(command, PlayFailedCommand):
                                        await service.play_failed(
                                            command_db,
                                            str(debate_id),
                                            expected_control_version=command.expected_control_version,
                                            epoch=str(command.controller_epoch),
                                            session_hash=_session_hash(fresh),
                                            turn_id=str(command.turn_id),
                                            failure_phase=command.failure_phase,
                                            cursor_ms=command.cursor_ms,
                                            safe_client_code=command.safe_client_code,
                                            context=fresh,
                                        )
                                    else:
                                        raise PlatformError(
                                            "malformed_command",
                                            "The command is not supported.",
                                            400,
                                        )
                                except PlatformError as exc:
                                    result = await service.command_duplicate_or_rejected(
                                        command_db,
                                        str(debate_id),
                                        command_id=str(command.command_id),
                                        code=exc.code,
                                        recoverable=exc.status_code in {408, 409, 503},
                                    )
                if result is not None:
                    await websocket.send_json(private_result_to_wire(result))
                if close_for_revocation:
                    await _close_ws(websocket, 4401)
                    break
                if event_task is None or event_task.done():
                    event_task = asyncio.create_task(stream.__anext__())
    except (WebSocketDisconnect, RuntimeError, PlatformError):
        pass
    finally:
        if event_task is not None:
            event_task.cancel()
        if receive_task is not None:
            receive_task.cancel()
        if epoch is not None:
            service.unregister_connection(epoch)
            with contextlib.suppress(Exception):
                with _websocket_session(database, settings) as disconnect_db:
                    await service.controller_disconnect(
                        disconnect_db,
                        str(debate_id),
                        epoch=epoch,
                        session_hash=session_hash(raw_token or ""),
                    )
        with contextlib.suppress(Exception):
            await stream.aclose()


@router.get(
    "/debates/{debate_id}/audio/{turn_id}",
    operation_id="streamRetainedTurnAudio",
    response_class=Response,
    responses={
        200: {
            "description": "Teacher-authorized complete retained audio.",
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Accept-Ranges": {"schema": {"type": "string", "const": "bytes"}},
                "ETag": {"schema": {"type": "string", "pattern": '^"[0-9a-f]{64}"$'}},
                "Content-Length": {"schema": {"type": "integer", "minimum": 0}},
            },
        },
        206: {
            "description": "Teacher-authorized single byte range of retained audio.",
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Accept-Ranges": {"schema": {"type": "string", "const": "bytes"}},
                "ETag": {"schema": {"type": "string", "pattern": '^"[0-9a-f]{64}"$'}},
                "Content-Length": {"schema": {"type": "integer", "minimum": 0}},
                "Content-Range": {
                    "schema": {
                        "type": "string",
                        "pattern": "^bytes [0-9]+-[0-9]+/[0-9]+$",
                    }
                },
            },
        },
        403: {"model": Error},
        404: {"model": Error},
        410: {"model": Error},
        416: {
            "description": "Requested byte range cannot be satisfied for this retained audio.",
            "model": Error,
            "headers": {
                "Content-Range": {"schema": {"type": "string", "pattern": r"^bytes \*/[0-9]+$"}}
            },
        },
    },
)
async def stream_audio_route(
    debate_id: UUID,
    turn_id: UUID,
    request: Request,
    range_header: Annotated[
        str,
        Header(alias="Range", pattern=r"^bytes=(?:[0-9]+-[0-9]*|-[0-9]+)$"),
    ] = None,  # type: ignore[assignment]
    if_range: Annotated[str, Header(alias="If-Range")] = None,  # type: ignore[assignment]
    media_ticket: Annotated[
        str,
        Query(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]{43}$"),
    ] = None,  # type: ignore[assignment]
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Response:
    if service.audio_store is None:
        raise not_found()
    await service.authorize_audio(
        db,
        str(debate_id),
        str(turn_id),
        session_hash=_session_hash(context),
        media_ticket=media_ticket,
        context=context,
    )
    try:
        result = service.audio_store.response(
            str(debate_id),
            str(turn_id),
            range_header=range_header,
            if_range=if_range,
        )
    except FileNotFoundError as exc:
        if str(exc) == "audio_not_retained":
            raise PlatformError(
                "audio_not_retained", "This audio is no longer retained.", 410
            ) from exc
        raise not_found() from exc
    if result.status_code == 416:
        request_id = UUID(str(getattr(request.state, "request_id", uuid4())))
        return JSONResponse(
            status_code=416,
            content=Error(
                code="range_not_satisfiable",
                message="The requested audio range is not satisfiable.",
                request_id=request_id,
            ).model_dump(mode="json"),
            headers=result.headers,
        )
    return Response(
        content=result.body,
        status_code=result.status_code,
        media_type="audio/wav",
        headers=result.headers,
    )


__all__ = ["get_playback_service", "router"]
