from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class CardRoom(Base):
    """One online Hold'em table, joined by its four-digit code.

    ``state_json`` holds the whole table, deck included, and never leaves the
    server as is: each player is sent a view with only their own cards.
    """

    __tablename__ = "card_rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(4))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    host_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    state_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(code) = 4 AND substr(code, 1, 1) BETWEEN '0' AND '9' "
            "AND substr(code, 2, 1) BETWEEN '0' AND '9' "
            "AND substr(code, 3, 1) BETWEEN '0' AND '9' "
            "AND substr(code, 4, 1) BETWEEN '0' AND '9'",
            name="ck_card_rooms_code",
        ),
        # A code names one open room at a time; closed rooms free it again.
        Index(
            "ux_card_rooms_open_code",
            "code",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_card_rooms_course_id", "course_id"),
    )
