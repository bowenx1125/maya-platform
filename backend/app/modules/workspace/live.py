"""Read-only classroom snapshots; spectators never acquire a teacher controller."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, WebSocket, WebSocketDisconnect
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import Error, PlatformError, conflict, not_found
from app.core.sqlutil import dialect_insert
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext, get_auth_context
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.playback.router import _websocket_origin_allowed, get_playback_service
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.round_count import debate_round_count, uses_segment_protocol
from app.modules.interactions.models import ClassroomInteractionWindow
from app.modules.interactions.tokens import issue_token

from .access import course_member
from .models import LivePresence
from .schemas import LiveHeartbeat, LiveParticipant, LiveSnapshot, LiveSummary, LiveTurn

router = APIRouter(
    tags=["Live"], responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}}
)


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
) -> LiveSummary | None:
    debate = db.get(Debate, str(debate_id))
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    course_member(db, context, debate.course_id, teacher=True)
    lease_id = str(payload.lease_id)
    if not payload.active:
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
    return LiveSummary(course_id=UUID(debate.course_id), debate_id=debate_id, topic=debate.topic)


@router.get(
    "/courses/{course_id}/live", response_model=LiveSummary | None, operation_id="getClassroomLive"
)
def live_status(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    service: PlaybackService = Depends(get_playback_service),
) -> LiveSummary | None:
    course_member(db, context, str(course_id))
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
    debate = db.get(Debate, debate_id)
    if debate is None or debate.deleted_at is not None:
        raise not_found()
    course_member(db, context, debate.course_id)
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
                avatar_config=AvatarConfig.model_validate_json(p.avatar_config_json),
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
) -> LiveSnapshot:
    return live_snapshot(db, service, str(debate_id), context)


@router.websocket("/live/{debate_id}/events")
async def live_events(websocket: WebSocket, debate_id: UUID) -> None:
    await websocket.accept()
    settings = websocket.app.state.settings
    if not _websocket_origin_allowed(websocket, settings):
        await websocket.close(code=4403)
        return
    database = websocket.app.state.database
    service = websocket.app.state.playback_service
    queue = await service.event_hub.subscribe(str(debate_id))
    incoming = asyncio.create_task(websocket.receive())
    previous = ""
    try:
        while True:
            with database.session() as db:
                context = get_auth_context(db, settings, websocket.cookies.get("maya_session"))
                if context is None:
                    await websocket.close(code=4401)
                    return
                snapshot = live_snapshot(db, service, str(debate_id), context)
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
            event = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait(
                    {event, incoming}, timeout=1, return_when=asyncio.FIRST_COMPLETED
                )
                if incoming in done:
                    await websocket.close(code=4403)
                    return
            finally:
                event.cancel()
                await asyncio.gather(event, return_exceptions=True)
    except PlatformError:
        await websocket.close(code=4403)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        incoming.cancel()
        await asyncio.gather(incoming, return_exceptions=True)
        await service.event_hub.unsubscribe(str(debate_id), queue)


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
