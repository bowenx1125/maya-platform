"""Online Hold'em tables for classmates, joined by a four-digit room code."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from . import service
from .schemas import CardAction, CardRoomView

router = APIRouter(
    tags=["Card rooms"],
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)

RoomCode = Path(pattern=r"^[0-9]{4}$", title="Code")


@router.post(
    "/card-rooms",
    response_model=CardRoomView,
    status_code=201,
    operation_id="createCardRoom",
    responses={409: {"model": Error}},
)
def create_card_room(
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.create_room(db, context, datetime.now(UTC))


@router.get(
    "/card-rooms/{code}",
    response_model=CardRoomView,
    operation_id="getCardRoom",
)
def get_card_room(
    code: str = RoomCode,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.get_room(db, context, code, datetime.now(UTC))


@router.post(
    "/card-rooms/{code}/seat",
    response_model=CardRoomView,
    operation_id="joinCardRoom",
    responses={409: {"model": Error}},
)
def join_card_room(
    code: str = RoomCode,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.join_room(db, context, code, datetime.now(UTC))


@router.delete(
    "/card-rooms/{code}/seat",
    status_code=204,
    operation_id="leaveCardRoom",
    response_class=Response,
    responses={409: {"model": Error}},
)
def leave_card_room(
    code: str = RoomCode,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Response:
    service.leave_room(db, context, code, datetime.now(UTC))
    return Response(status_code=204)


@router.post(
    "/card-rooms/{code}/start",
    response_model=CardRoomView,
    operation_id="startCardRoom",
    responses={409: {"model": Error}},
)
def start_card_room(
    code: str = RoomCode,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.start_room(db, context, code, datetime.now(UTC))


@router.post(
    "/card-rooms/{code}/actions",
    response_model=CardRoomView,
    operation_id="actInCardRoom",
    responses={409: {"model": Error}},
)
def act_in_card_room(
    payload: CardAction,
    code: str = RoomCode,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.act_in_room(
        db,
        context,
        code,
        payload.type,
        payload.to,
        payload.expected_revision,
        datetime.now(UTC),
    )


@router.post(
    "/card-rooms/{code}/rebuy",
    response_model=CardRoomView,
    operation_id="rebuyInCardRoom",
    responses={409: {"model": Error}},
)
def rebuy_in_card_room(
    code: str = RoomCode,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> CardRoomView:
    return service.rebuy_in_room(db, context, code, datetime.now(UTC))
