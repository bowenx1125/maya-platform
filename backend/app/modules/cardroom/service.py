"""Online card rooms: codes, seats, the clock, and what each player may see.

Nothing runs in the background. Everyone at a table polls once a second, and
every request first settles whatever the clock has made due: a player whose 60
seconds ran out checks or folds, and a finished hand is followed by the next
six seconds later. Writers take SQLite's writer lock before reading the room,
and a write only lands on the revision it read, so two players' polls can
never settle the same moment twice.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, not_found, stale_revision
from app.core.models import CourseMember
from app.core.sqlutil import begin_immediate
from app.modules.auth.service import AuthContext
from app.modules.workspace.access import course_member

from .engine import (
    ActionType,
    Card,
    RuleError,
    Seat,
    Table,
    act,
    create_table,
    legal_actions,
    pot,
    start_hand,
)
from .models import CardRoom
from .schemas import CardLegalView, CardPayoutView, CardRoomView, CardSeatView, CardView

SEATS = 6
STACK = 4000
SMALL_BLIND = 10
BIG_BLIND = 20
TURN = timedelta(seconds=60)
BETWEEN_HANDS = timedelta(seconds=6)
# A room nobody has touched for this long is abandoned and frees its code.
IDLE = timedelta(hours=6)
# Let the clock run out twice in a row and you are taken off the table.
MAX_MISSED = 2


@dataclass
class RoomState:
    table: Table
    host: str
    started: bool = False
    deadline: datetime | None = None
    next_hand_at: datetime | None = None
    missed: dict[str, int] = field(default_factory=dict)
    leaving: list[str] = field(default_factory=list)

    def dump(self) -> str:
        return json.dumps(
            {
                "table": self.table.to_dict(),
                "host": self.host,
                "started": self.started,
                "deadline": self.deadline.isoformat() if self.deadline else None,
                "next_hand_at": self.next_hand_at.isoformat() if self.next_hand_at else None,
                "missed": self.missed,
                "leaving": self.leaving,
            }
        )

    @classmethod
    def load(cls, raw: str) -> RoomState:
        data: dict[str, Any] = json.loads(raw)

        def moment(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return cls(
            table=Table.from_dict(data["table"]),
            host=data["host"],
            started=data["started"],
            deadline=moment(data["deadline"]),
            next_hand_at=moment(data["next_hand_at"]),
            missed=data["missed"],
            leaving=data["leaving"],
        )


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes for timezone-aware columns.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _lock(db: Session) -> None:
    """Take SQLite's writer lock before the room is read for a write."""

    if db.get_bind().dialect.name != "sqlite":
        return
    db.rollback()
    try:
        begin_immediate(db)
    except OperationalError:
        raise conflict("card_room_busy", "The table is busy; try again.") from None


def _load(
    db: Session, context: AuthContext, code: str, now: datetime
) -> tuple[CardRoom, RoomState]:
    room = db.scalar(select(CardRoom).where(CardRoom.code == code, CardRoom.closed_at.is_(None)))
    # Another course's room, and an abandoned one, simply do not exist.
    if room is None or _aware(room.updated_at) < now - IDLE:
        raise not_found()
    course_member(db, context, room.course_id)
    return room, RoomState.load(room.state_json)


def _save(db: Session, room: CardRoom, state: RoomState, now: datetime) -> None:
    result = db.execute(
        update(CardRoom)
        .where(CardRoom.id == room.id, CardRoom.revision == room.revision)
        .values(
            state_json=state.dump(),
            host_user_id=state.host,
            revision=room.revision + 1,
            updated_at=now,
            # The last player out closes the room and frees its code.
            closed_at=None if state.table.seats else now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("card_room_busy", "The table moved on; try again.")
    db.refresh(room)


def _ready(state: RoomState) -> bool:
    return sum(1 for seat in state.table.seats if seat.stack > 0) >= 2


def _after_move(state: RoomState, when: datetime) -> None:
    if state.table.street == "complete":
        state.deadline = None
        state.next_hand_at = when + BETWEEN_HANDS
    else:
        state.deadline = when + TURN
        state.next_hand_at = None


def _drop_leavers(state: RoomState) -> None:
    """Between hands, take everyone who left or timed out off the table."""

    table = state.table
    keep: list[Seat] = []
    for index, seat in enumerate(table.seats):
        if seat.id in state.leaving:
            # The button stays put, so the next hand passes it on fairly.
            if index <= table.button:
                table.button -= 1
            state.missed.pop(seat.id, None)
        else:
            keep.append(seat)
    table.seats = keep
    state.leaving = []
    if table.seats and state.host not in {seat.id for seat in table.seats}:
        state.host = table.seats[0].id


def _settle(state: RoomState, now: datetime) -> bool:
    """Apply everything the clock has made due by ``now``."""

    changed = False
    # Bounded: every pass is one move or one deal.
    for _ in range(256):
        table = state.table
        if table.to_act is not None:
            seat = table.seats[table.to_act]
            gone = seat.id in state.leaving
            if not gone and (state.deadline is None or state.deadline > now):
                break
            if gone:
                # Someone who left gives up the hand rather than playing on.
                state.table = act(table, "fold")
                when = now
            else:
                state.table = act(table, "check" if legal_actions(table).can_check else "fold")
                state.missed[seat.id] = state.missed.get(seat.id, 0) + 1
                if state.missed[seat.id] >= MAX_MISSED:
                    state.leaving.append(seat.id)
                when = state.deadline or now
            _after_move(state, when)
            changed = True
        elif state.next_hand_at is not None and state.next_hand_at <= now:
            when = state.next_hand_at
            _drop_leavers(state)
            if _ready(state):
                state.table = start_hand(state.table)
                _after_move(state, when)
            else:
                state.next_hand_at = None
            changed = True
        else:
            break
    return changed


def _card(card: Card) -> CardView:
    return CardView(rank=card.rank, suit=card.suit)


def view(room: CardRoom, state: RoomState, viewer: str, now: datetime) -> CardRoomView:
    table = state.table
    you = next((i for i, seat in enumerate(table.seats) if seat.id == viewer), None)
    shown = table.street == "complete" and table.showdown

    def hole(seat: Seat) -> list[CardView]:
        # Your own cards always; anyone else's only once a showdown shows them.
        if seat.id == viewer or (shown and not seat.folded):
            return [_card(card) for card in seat.hole]
        return []

    legal = None
    if you is not None and table.to_act == you:
        rules = legal_actions(table)
        legal = CardLegalView(
            can_check=rules.can_check,
            to_call=rules.to_call,
            can_raise=rules.can_raise,
            min_raise_to=rules.min_raise_to,
            max_raise_to=rules.max_raise_to,
        )
    return CardRoomView(
        code=room.code,
        status="playing" if state.started else "waiting",
        revision=room.revision,
        you=you,
        seats=[
            CardSeatView(
                user_id=UUID(seat.id),
                name=seat.name,
                avatar=seat.avatar,
                stack=seat.stack,
                bet=seat.bet,
                folded=seat.folded,
                all_in=seat.all_in,
                sitting_out=seat.sitting_out,
                last_action=seat.last_action,
                hole=hole(seat),
                hole_count=len(seat.hole),
                host=seat.id == state.host,
                leaving=seat.id in state.leaving,
            )
            for seat in table.seats
        ],
        board=[_card(card) for card in table.board],
        pot=pot(table),
        button=table.button if table.hand_number else None,
        to_act=table.to_act,
        street=table.street,
        current_bet=table.current_bet,
        small_blind=table.small_blind,
        big_blind=table.big_blind,
        hand_number=table.hand_number,
        legal=legal,
        now=now,
        deadline=state.deadline,
        next_hand_at=state.next_hand_at,
        payouts=[
            CardPayoutView(user_id=UUID(payout.seat_id), amount=payout.amount, hand=payout.hand)
            for payout in table.payouts
        ],
        showdown=table.showdown,
    )


def _open(
    db: Session, context: AuthContext, code: str, now: datetime
) -> tuple[CardRoom, RoomState, bool]:
    """Lock, read, and settle a room that is about to be changed."""

    _lock(db)
    room, state = _load(db, context, code, now)
    return room, state, _settle(state, now)


def create_room(db: Session, context: AuthContext, now: datetime) -> CardRoomView:
    _lock(db)
    user = context.user
    # Abandoned rooms give their codes back before a new one is drawn.
    db.execute(
        update(CardRoom)
        .where(CardRoom.closed_at.is_(None), CardRoom.updated_at < now - IDLE)
        .values(closed_at=now)
        .execution_options(synchronize_session=False)
    )
    hosting = db.scalar(
        select(CardRoom).where(CardRoom.host_user_id == user.id, CardRoom.closed_at.is_(None))
    )
    if hosting is not None:
        # One open room per host: opening again brings you back to it.
        return view(hosting, RoomState.load(hosting.state_json), user.id, now)
    # The room belongs to the course you joined first; its classmates may sit down.
    membership = db.scalar(
        select(CourseMember)
        .where(CourseMember.user_id == user.id)
        .order_by(CourseMember.created_at, CourseMember.course_id)
    )
    if membership is None:
        raise forbidden("Join a course before opening a card room.")
    taken = set(db.scalars(select(CardRoom.code).where(CardRoom.closed_at.is_(None))))
    free = [f"{n:04d}" for n in range(10_000) if f"{n:04d}" not in taken]
    if not free:
        raise conflict("card_room_codes_exhausted", "Every room code is in use right now.")
    code = free[secrets.randbelow(len(free))]
    state = RoomState(
        table=create_table(
            [(user.id, user.display_name, user.avatar)],
            stack=STACK,
            small_blind=SMALL_BLIND,
            big_blind=BIG_BLIND,
        ),
        host=user.id,
    )
    room = CardRoom(
        id=str(uuid4()),
        code=code,
        course_id=membership.course_id,
        host_user_id=user.id,
        state_json=state.dump(),
        revision=0,
        created_at=now,
        updated_at=now,
    )
    db.add(room)
    try:
        db.flush()
    except IntegrityError:
        raise conflict("card_room_busy", "That room code was just taken; try again.") from None
    return view(room, state, user.id, now)


def get_room(db: Session, context: AuthContext, code: str, now: datetime) -> CardRoomView:
    room, state = _load(db, context, code, now)
    if _settle(state, now):
        # The clock moved the table on; write that under the lock, from a fresh
        # read, unless another player's poll already has.
        room, state, settled = _open(db, context, code, now)
        if settled:
            _save(db, room, state, now)
    return view(room, state, context.user.id, now)


def join_room(db: Session, context: AuthContext, code: str, now: datetime) -> CardRoomView:
    room, state, _ = _open(db, context, code, now)
    user = context.user
    table = state.table
    if any(seat.id == user.id for seat in table.seats):
        # Sitting back down before your leave took effect keeps your seat.
        if user.id in state.leaving:
            state.leaving.remove(user.id)
        state.missed.pop(user.id, None)
    elif len(table.seats) >= SEATS:
        raise conflict("card_room_full", "This table is full.")
    else:
        # Sitting down mid-hand, you watch it out and are dealt the next one.
        playing = table.street not in ("waiting", "complete")
        table.seats.append(
            Seat(
                id=user.id,
                name=user.display_name,
                avatar=user.avatar,
                stack=STACK,
                sitting_out=playing,
            )
        )
    if state.started and table.to_act is None and state.next_hand_at is None and _ready(state):
        state.next_hand_at = now + BETWEEN_HANDS
    _save(db, room, state, now)
    return view(room, state, user.id, now)


def leave_room(db: Session, context: AuthContext, code: str, now: datetime) -> None:
    room, state, _ = _open(db, context, code, now)
    user = context.user.id
    table = state.table
    if not any(seat.id == user for seat in table.seats):
        return
    if user not in state.leaving:
        state.leaving.append(user)
    if table.street in ("waiting", "complete"):
        _drop_leavers(state)
    elif all(seat.id in state.leaving for seat in table.seats):
        # Everyone is gone; there is nobody left to finish the hand for.
        table.seats = []
    else:
        _settle(state, now)
        if state.host == user:
            stay = [seat.id for seat in state.table.seats if seat.id not in state.leaving]
            state.host = stay[0]
    _save(db, room, state, now)


def start_room(db: Session, context: AuthContext, code: str, now: datetime) -> CardRoomView:
    room, state, _ = _open(db, context, code, now)
    if state.host != context.user.id:
        raise forbidden("Only the host deals the first hand.")
    if state.started:
        raise conflict("card_room_started", "This table is already playing.")
    if not _ready(state):
        raise conflict("card_room_needs_players", "A hand needs two players with chips.")
    state.started = True
    state.table = start_hand(state.table)
    _after_move(state, now)
    _save(db, room, state, now)
    return view(room, state, context.user.id, now)


def act_in_room(
    db: Session,
    context: AuthContext,
    code: str,
    action: ActionType,
    to: int | None,
    expected_revision: int,
    now: datetime,
) -> CardRoomView:
    room, state, settled = _open(db, context, code, now)
    table = state.table
    # A move is made on the table you saw; if the clock or anyone else has
    # moved it on since, you are shown the new one instead.
    if settled or room.revision != expected_revision:
        raise stale_revision(room.revision)
    if table.to_act is None or table.seats[table.to_act].id != context.user.id:
        raise conflict("card_room_not_your_turn", "It is not your turn.")
    try:
        state.table = act(table, action, to)
    except RuleError as exc:
        raise conflict("card_room_illegal_action", str(exc)) from None
    state.missed.pop(context.user.id, None)
    _after_move(state, now)
    _save(db, room, state, now)
    return view(room, state, context.user.id, now)


def rebuy_in_room(db: Session, context: AuthContext, code: str, now: datetime) -> CardRoomView:
    room, state, _ = _open(db, context, code, now)
    table = state.table
    seat = next((seat for seat in table.seats if seat.id == context.user.id), None)
    if seat is None:
        raise conflict("card_room_not_seated", "Sit down before buying chips.")
    if seat.stack > 0 or table.street not in ("waiting", "complete"):
        raise conflict(
            "card_room_rebuy_not_allowed",
            "Chips are topped up only when you have none, between hands.",
        )
    seat.stack = STACK
    seat.sitting_out = False
    if state.started and state.next_hand_at is None and _ready(state):
        state.next_hand_at = now + BETWEEN_HANDS
    _save(db, room, state, now)
    return view(room, state, context.user.id, now)
