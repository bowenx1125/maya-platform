"""Read-only classroom snapshots; spectators never acquire a teacher controller."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.adaptive_admission import polling_pressure
from app.core.config import Settings, get_settings
from app.core.debate_gate import PublicCopy
from app.core.errors import Error, PlatformError, conflict, not_found
from app.core.sqlutil import dialect_insert
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext, get_auth_context
from app.modules.debates.display_avatar import participant_display_avatar
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.playback.router import _websocket_origin_allowed, get_playback_service
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.round_count import debate_round_count, uses_segment_protocol
from app.modules.interactions.models import ClassroomInteractionWindow
from app.modules.interactions.tokens import issue_token

from .access import course_member
from .live_push import CourseLiveWatcher, as_message
from .models import LivePresence
from .schemas import LiveHeartbeat, LiveParticipant, LiveSnapshot, LiveSummary, LiveTurn

router = APIRouter(
    tags=["Live"], responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}}
)

# A heartbeat for the same lease/session/epoch acknowledged this recently is
# answered from memory while the server sheds load (the lease lasts 20 s).
HEARTBEAT_ACK_SECONDS = 10.0
_HEARTBEAT_ACKS: dict[tuple[str, str, str, str], tuple[float, LiveSummary]] = {}
# Per-process copies of the course live status and the audience view.
_PUBLIC = PublicCopy()


def reset_live_caches() -> None:
    """Forget cached live answers (tests only)."""

    _HEARTBEAT_ACKS.clear()
    _PUBLIC.clear()


@router.post(
    "/debates/{debate_id}/live",
    response_model=LiveSummary | None,
    operation_id="updateClassroomLive",
    responses={409: {"model": Error}},
)
def heartbeat(
    debate_id: UUID,
    payload: LiveHeartbeat,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
    settings: Settings = Depends(get_settings),
) -> LiveSummary | None:
    if payload.active and polling_pressure(settings):
        # Under pressure the same lease, session and controller epoch that
        # was refreshed within HEARTBEAT_ACK_SECONDS is acknowledged from
        # memory: the 20 s lease is still valid, so one write per ~10 s keeps
        # the broadcast alive at a fraction of the database work.
        ack = _HEARTBEAT_ACKS.get(
            (
                str(debate_id),
                str(payload.lease_id),
                context.session.id_hash,
                str(payload.controller_epoch),
            )
        )
        if ack is not None and time.monotonic() - ack[0] < HEARTBEAT_ACK_SECONDS:
            return ack[1]
    debate = db.get(Debate, str(debate_id))
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    course_member(db, context, debate.course_id, teacher=True)
    lease_id = str(payload.lease_id)
    ack_key = (str(debate_id), lease_id, context.session.id_hash, str(payload.controller_epoch))
    if not payload.active:
        _HEARTBEAT_ACKS.pop(ack_key, None)
        db.execute(
            delete(LivePresence).where(
                LivePresence.course_id == debate.course_id,
                LivePresence.lease_id == lease_id,
                LivePresence.session_hash == context.session.id_hash,
            )
        )
        return None
    state = service._state(db, debate)
    if debate.status in {"stopped", "failed"} or state.status == "stopped":
        raise conflict("live_not_active", "This classroom is not broadcasting.")
    # A finished lesson stays watchable while this page is open. It has no
    # playback controller, so the epoch check would hide Live.
    if debate.status != "draft" and state.status != "completed":
        service._check_epoch(
            state, epoch=str(payload.controller_epoch), session_hash=context.session.id_hash
        )
    now = datetime.now(UTC)
    current = db.get(LivePresence, debate.course_id)
    if current and current.lease_id != lease_id and current.expires_at.replace(tzinfo=UTC) > now:
        # The existing controller owns handoff during playback. A ready page
        # has no controller yet, so it cannot evict another teacher's lease.
        if debate.status == "draft":
            raise conflict("live_already_active", "Another classroom is broadcasting.")
    values = dict(
        course_id=debate.course_id,
        debate_id=debate.id,
        session_hash=context.session.id_hash,
        lease_id=lease_id,
        expires_at=now + timedelta(seconds=20),
    )
    db.execute(
        dialect_insert(db, LivePresence)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[LivePresence.course_id],
            set_=values,
        )
    )
    summary = LiveSummary(course_id=UUID(debate.course_id), debate_id=debate_id, topic=debate.topic)
    _HEARTBEAT_ACKS[ack_key] = (time.monotonic(), summary)
    return summary


@router.get(
    "/courses/{course_id}/live", response_model=LiveSummary | None, operation_id="getClassroomLive"
)
def live_status(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
    settings: Settings = Depends(get_settings),
) -> LiveSummary | None:
    course_member(db, context, str(course_id))

    def load() -> tuple[LiveSummary | None]:
        return (_live_status(db, service, course_id),)

    # Every student page polls this. The answer is the same for the whole
    # course: a copy for a couple of seconds, a stale one under pressure.
    return cast(
        tuple[LiveSummary | None],
        _PUBLIC.read(("live_status", str(course_id)), settings, load, what="live_status"),
    )[0]


def _live_statuses(
    database: Any, service: PlaybackService, courses: list[str]
) -> dict[str, LiveSummary | None]:
    """Live status for many courses: one presence query, then only live ones."""

    now = datetime.now(UTC)
    result: dict[str, LiveSummary | None] = {}
    with database.session() as db:
        rows = db.scalars(select(LivePresence).where(LivePresence.course_id.in_(courses))).all()
        for row in rows:
            if row.expires_at.replace(tzinfo=UTC) > now:
                result[str(row.course_id)] = _live_status(db, service, UUID(str(row.course_id)))
    return result


def course_live_watcher(app: Any) -> CourseLiveWatcher:
    """The one per-process watcher (created on first subscriber)."""

    watcher = getattr(app.state, "course_live_watcher", None)
    if watcher is None:
        database = app.state.database
        service = app.state.playback_service
        watcher = CourseLiveWatcher(lambda courses: _live_statuses(database, service, courses))
        app.state.course_live_watcher = watcher
    return cast(CourseLiveWatcher, watcher)


@router.websocket("/courses/{course_id}/live/events")
async def course_live_events(websocket: WebSocket, course_id: UUID) -> None:
    """Pushes ``{"live": LiveSummary | null}`` now and on every change.

    Replaces the student shell's 5 s poll of ``GET /courses/{id}/live``.
    Close 4429 means this process is full; the client keeps its slow poll.
    """

    await websocket.accept()
    settings = websocket.app.state.settings
    if not _websocket_origin_allowed(websocket, settings):
        await websocket.close(code=4403)
        return
    database = websocket.app.state.database
    service = websocket.app.state.playback_service
    key = str(course_id)
    recheck = float(settings.debate_ws_auth_recheck_seconds)
    raw_token = websocket.cookies.get("maya_session")

    def authorized() -> bool:
        with database.session() as db:
            context = get_auth_context(db, settings, raw_token)
            if context is None:
                return False
            try:
                course_member(db, context, key)
            except PlatformError:
                return False
            return True

    if not await asyncio.to_thread(authorized):
        await websocket.close(code=4401)
        return
    watcher = course_live_watcher(websocket.app)
    queue = await watcher.subscribe(key)
    if queue is None:
        await websocket.close(code=4429)
        return
    incoming = asyncio.create_task(websocket.receive())
    last_authorized = time.monotonic()
    try:
        initial = await asyncio.to_thread(_live_statuses, database, service, [key])
        await websocket.send_json(as_message(initial.get(key)))
        while True:
            timeout = max(0.05, recheck - (time.monotonic() - last_authorized))
            change = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait(
                    {change, incoming}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if incoming in done:
                    # Read-only: any client frame or a close ends the stream.
                    await websocket.close(code=1000)
                    return
                if change in done:
                    value = change.result()
                    while not queue.empty():
                        value = queue.get_nowait()
                    await websocket.send_json(as_message(value))
            finally:
                change.cancel()
                await asyncio.gather(change, return_exceptions=True)
            if time.monotonic() - last_authorized >= recheck:
                if not await asyncio.to_thread(authorized):
                    await websocket.close(code=4401)
                    return
                last_authorized = time.monotonic()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)
        await watcher.unsubscribe(key, queue)


def _live_status(db: Session, service: PlaybackService, course_id: UUID) -> LiveSummary | None:
    presence = db.get(LivePresence, str(course_id))
    if presence is None or presence.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        return None
    debate = db.get(Debate, presence.debate_id)
    if debate is None or debate.deleted_at is not None or debate.status in {"stopped", "failed"}:
        return None
    if service._state(db, debate).status == "stopped":
        return None
    return LiveSummary(course_id=course_id, debate_id=UUID(debate.id), topic=debate.topic)


def live_snapshot(
    db: Session, service: PlaybackService, debate_id: str, context: AuthContext
) -> LiveSnapshot:
    live_access(db, debate_id, context)
    return live_view(db, service, debate_id)


def live_access(db: Session, debate_id: str, context: AuthContext) -> str:
    """The viewer may watch this Debate's course; returns the course id."""

    debate = db.get(Debate, debate_id)
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    course_member(db, context, debate.course_id)
    return str(debate.course_id)


def live_view(db: Session, service: PlaybackService, debate_id: str) -> LiveSnapshot:
    """The audience snapshot, the same for every viewer (access checked apart)."""

    debate = db.get(Debate, debate_id)
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    presence = db.get(LivePresence, debate.course_id)
    now = datetime.now(UTC)
    state = service._state(db, debate)
    active = bool(
        presence
        and presence.debate_id == debate_id
        and presence.expires_at.replace(tzinfo=UTC) > now
        and state.status != "stopped"
    )
    participants = (
        db.scalars(
            select(DebateParticipant)
            .where(
                DebateParticipant.debate_id == debate_id,
            )
            .order_by(DebateParticipant.order_index)
        ).all()
        if active
        else []
    )
    turns = (
        db.scalars(
            select(DebateTurn)
            .where(
                DebateTurn.debate_id == debate_id,
                DebateTurn.publication_status == "public",
                DebateTurn.generation_status == "final_ready",
            )
            .order_by(DebateTurn.turn_index)
        ).all()
        if active
        else []
    )
    interaction_url = None
    if (
        active
        and state.mode == "live"
        and debate.final_input_json is None
        and service.settings is not None
    ):
        window = db.scalar(
            select(ClassroomInteractionWindow).where(
                ClassroomInteractionWindow.debate_id == debate_id,
                ClassroomInteractionWindow.course_id == debate.course_id,
                ClassroomInteractionWindow.status == "open",
            )
        )
        current = db.get(DebateTurn, state.current_turn_id) if state.current_turn_id else None
        collecting = not uses_segment_protocol(debate) or (
            debate.status == "running"
            and current is not None
            and current.round_no < debate_round_count(debate)
        )
        if window is not None and window.token_nonce is not None and collecting:
            token = issue_token(window.id, bytes(window.token_nonce), service.settings.secret_bytes)
            interaction_url = f"/classroom/{token}"
    return LiveSnapshot(
        interaction_url=interaction_url,
        active=active,
        debate_id=UUID(debate_id),
        sequence=debate.last_sequence,
        server_time=now,
        participants=[
            LiveParticipant(
                id=UUID(p.id),
                name=p.agent_name,
                avatar_config=AvatarConfig.model_validate(participant_display_avatar(db, p)),
            )
            for p in participants
        ],
        turns=[
            LiveTurn(
                id=UUID(t.id),
                participant_id=UUID(t.participant_id),
                round_no=t.round_no,
                turn_index=t.turn_index,
                speech=t.speech or "",
                audio_url=f"/api/v1/live/{debate_id}/audio/{t.id}" if t.audio_file_id else None,
            )
            for t in turns
        ],
        playback=service._state_dto(state, db, debate) if active else None,
    )


@router.get("/live/{debate_id}", response_model=LiveSnapshot, operation_id="getLiveSnapshot")
def get_live_snapshot(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
    settings: Settings = Depends(get_settings),
) -> LiveSnapshot:
    key = str(debate_id)
    live_access(db, key, context)
    view = cast(
        LiveSnapshot,
        _PUBLIC.read(
            ("live_view", key),
            settings,
            lambda: live_view(db, service, key),
            what="live_view",
            # A Debate event (local or relayed) retires the fresh copy at
            # once; under pressure an older copy is still served.
            version=service.event_hub.version(key),
        ),
    )
    return view.model_copy(update={"server_time": datetime.now(UTC)})


@router.websocket("/live/{debate_id}/events")
async def live_events(websocket: WebSocket, debate_id: UUID) -> None:
    """Audience stream: woken by Debate events, never one query per viewer per tick.

    Load plan 2026-10-19: every viewer's socket used to read the database once
    a second. Now the audience view is one per-process copy per Debate
    (rebuilt at most every ``DEBATE_SNAPSHOT_CACHE_SECONDS``), sockets wake on
    events (local, or relayed from the other backend) with a fallback poll of
    ``DEBATE_WS_FALLBACK_POLL_SECONDS``, and access is rechecked every
    ``DEBATE_WS_AUTH_RECHECK_SECONDS``.
    """

    await websocket.accept()
    settings = websocket.app.state.settings
    if not _websocket_origin_allowed(websocket, settings):
        await websocket.close(code=4403)
        return
    database = websocket.app.state.database
    service = websocket.app.state.playback_service
    hub = service.event_hub
    key = str(debate_id)
    cache_key = (key, "audience")
    ttl = float(settings.debate_snapshot_cache_seconds)
    recheck = float(settings.debate_ws_auth_recheck_seconds)
    fallback = float(settings.debate_ws_fallback_poll_seconds)
    raw_token = websocket.cookies.get("maya_session")

    def authorized() -> bool:
        with database.session() as db:
            context = get_auth_context(db, settings, raw_token)
            if context is None:
                return False
            live_access(db, key, context)
            return True

    async def build() -> LiveSnapshot:
        def read() -> LiveSnapshot:
            with database.session() as db:
                return live_view(db, service, key)

        return await asyncio.to_thread(read)

    queue = await hub.subscribe(key)
    incoming = asyncio.create_task(websocket.receive())
    previous = ""
    last_authorized: float | None = None
    try:
        while True:
            if last_authorized is None or time.monotonic() - last_authorized >= recheck:
                if not await asyncio.to_thread(authorized):
                    await websocket.close(code=4401)
                    return
                last_authorized = time.monotonic()
            shared, built_version = await hub.snapshots.get(cache_key, ttl, hub.version(key), build)
            snapshot = cast(LiveSnapshot, shared).model_copy(
                update={"server_time": datetime.now(UTC)}
            )
            comparable = snapshot.model_dump(mode="json", exclude={"server_time", "playback"})
            if snapshot.playback:
                comparable["playback"] = snapshot.playback.model_dump(
                    mode="json", exclude={"cursor_ms"}
                )
            fingerprint = json.dumps(comparable, sort_keys=True)
            if fingerprint != previous:
                await websocket.send_json(snapshot.model_dump(mode="json"))
                previous = fingerprint
            if not snapshot.active:
                await websocket.close(code=1000)
                return
            timeout = fallback
            if built_version < hub.version(key):
                # The shared copy predates an event: look again when it expires.
                age = hub.snapshots.age(cache_key) or 0.0
                timeout = max(0.05, ttl - age)
            event = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait(
                    {event, incoming}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if incoming in done:
                    await websocket.close(code=4403)
                    return
            finally:
                event.cancel()
                await asyncio.gather(event, return_exceptions=True)
            # A burst of events is one wake-up.
            while not queue.empty():
                queue.get_nowait()
    except PlatformError:
        await websocket.close(code=4403)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)
        await hub.unsubscribe(key, queue)


@router.get(
    "/live/{debate_id}/audio/{turn_id}",
    operation_id="getLiveAudio",
    responses={
        200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}},
        206: {
            "description": "Partial audio",
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        },
        416: {"description": "Unsatisfiable range"},
    },
)
def live_audio(
    debate_id: UUID,
    turn_id: UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> Response:
    snapshot = live_snapshot(db, service, str(debate_id), context)
    if not snapshot.active or not any(t.id == turn_id and t.audio_url for t in snapshot.turns):
        raise not_found()
    if service.audio_store is None:
        raise not_found()
    debate = db.get(Debate, str(debate_id))
    turn = db.get(DebateTurn, str(turn_id))
    if debate is None or turn is None or service._validated_turn_audio(db, debate, turn) is None:
        raise not_found()
    try:
        result = service.audio_store.response(
            str(debate_id), str(turn_id), range_header=range_header, if_range=None
        )
    except FileNotFoundError:
        raise not_found() from None
    return Response(
        result.body,
        status_code=result.status_code,
        media_type="audio/wav",
        headers={**result.headers, "Cache-Control": "private, no-store"},
    )
