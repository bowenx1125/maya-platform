from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardView(ClosedModel):
    rank: int = Field(ge=2, le=14)
    suit: Literal["s", "h", "d", "c"]


class CardSeatView(ClosedModel):
    user_id: UUID
    name: str
    avatar: str | None = None
    stack: int
    bet: int
    folded: bool
    all_in: bool
    sitting_out: bool
    last_action: str | None = None
    # Your own cards always; anyone else's only once a showdown has shown them.
    hole: list[CardView]
    hole_count: int
    host: bool
    leaving: bool


class CardLegalView(ClosedModel):
    can_check: bool
    to_call: int
    can_raise: bool
    min_raise_to: int
    max_raise_to: int


class CardPayoutView(ClosedModel):
    user_id: UUID
    amount: int
    hand: str | None = None


class CardRoomView(ClosedModel):
    code: str = Field(pattern=r"^[0-9]{4}$")
    status: Literal["waiting", "playing"]
    revision: int
    you: int | None = None
    seats: list[CardSeatView]
    board: list[CardView]
    pot: int
    button: int | None = None
    to_act: int | None = None
    street: Literal["waiting", "preflop", "flop", "turn", "river", "complete"]
    current_bet: int
    small_blind: int
    big_blind: int
    hand_number: int
    legal: CardLegalView | None = None
    # The server's clock, so every player counts the same 60 seconds down.
    now: datetime
    deadline: datetime | None = None
    next_hand_at: datetime | None = None
    payouts: list[CardPayoutView]
    showdown: bool


class CardAction(ClosedModel):
    type: Literal["fold", "check", "call", "raise"]
    to: int | None = Field(default=None, ge=1)
    expected_revision: int = Field(ge=0)
