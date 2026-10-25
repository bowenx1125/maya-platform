"""Playback media tickets in PostgreSQL, shared by every backend replica (PR C).

The in-memory ``MediaTicketStore`` only knew the tickets its own process
issued. Production runs two replicas behind a sticky cookie; when a replica
restarted, the browser moved to the other one and every open ticket (the
current speech and the queued downloads) answered 403. This store keeps the
same hash-only bindings in ``playback_media_tickets``: the raw token is never
stored, each call is one short transaction, and expired rows are pruned when
new tickets are issued.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules.debates.models import PlaybackMediaTicket

from .audio import (
    MEDIA_TICKET_BYTES,
    MEDIA_TICKET_GRACE,
    MEDIA_TICKET_TTL,
    MediaTicketBinding,
    MediaTicketStore,
    _utc,
)


def _binding(row: PlaybackMediaTicket) -> MediaTicketBinding:
    return MediaTicketBinding(
        token_hash=row.token_hash,
        session_hash=row.session_hash,
        controller_epoch=row.controller_epoch,
        debate_id=row.debate_id,
        turn_id=row.turn_id,
        action=row.action,  # type: ignore[arg-type]
        control_version=row.control_version,
        issued_at=_utc(row.issued_at),
        expires_at=_utc(row.expires_at),
        started=row.started,
    )


class SqlMediaTicketStore(MediaTicketStore):
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        ttl: timedelta = MEDIA_TICKET_TTL,
    ) -> None:
        super().__init__(ttl=ttl)
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def issue(
        self,
        *,
        session_hash: str,
        controller_epoch: str,
        debate_id: str,
        turn_id: str,
        action: Literal["start", "resume", "next", "replay", "prefetch"],
        control_version: int = 0,
        now: datetime | None = None,
    ) -> tuple[str, MediaTicketBinding]:
        issued = _utc(now or datetime.now(UTC))
        token = secrets.token_urlsafe(MEDIA_TICKET_BYTES)
        if len(token) != 43:
            raise RuntimeError("media ticket generator returned an invalid token")
        row = PlaybackMediaTicket(
            token_hash=self._hash(token),
            session_hash=session_hash,
            controller_epoch=controller_epoch,
            debate_id=debate_id,
            turn_id=turn_id,
            action=action,
            control_version=control_version,
            issued_at=issued,
            expires_at=issued + self.ttl,
            started=False,
        )
        with self._session() as session:
            session.execute(
                delete(PlaybackMediaTicket).where(PlaybackMediaTicket.expires_at < issued)
            )
            session.add(row)
            session.flush()
            binding = _binding(row)
        return token, binding

    def get(self, token: str, *, now: datetime | None = None) -> MediaTicketBinding | None:
        if len(token) != 43 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return None
        current = _utc(now or datetime.now(UTC))
        with self._session() as session:
            row = session.get(PlaybackMediaTicket, self._hash(token))
            if row is None:
                return None
            if current > _utc(row.expires_at):
                session.delete(row)
                return None
            return _binding(row)

    def find(
        self,
        *,
        session_hash: str,
        controller_epoch: str,
        debate_id: str,
        turn_id: str,
        action: str,
        started: bool | None = None,
        now: datetime | None = None,
    ) -> tuple[str, MediaTicketBinding] | None:
        current = _utc(now or datetime.now(UTC))
        query = select(PlaybackMediaTicket).where(
            PlaybackMediaTicket.session_hash == session_hash,
            PlaybackMediaTicket.controller_epoch == controller_epoch,
            PlaybackMediaTicket.debate_id == debate_id,
            PlaybackMediaTicket.turn_id == turn_id,
            PlaybackMediaTicket.action == action,
            PlaybackMediaTicket.expires_at >= current,
        )
        if started is not None:
            query = query.where(PlaybackMediaTicket.started.is_(started))
        with self._session() as session:
            row = session.scalars(query.order_by(PlaybackMediaTicket.issued_at).limit(1)).first()
            return (row.token_hash, _binding(row)) if row is not None else None

    def mark_binding_started(
        self,
        binding: MediaTicketBinding,
        *,
        now: datetime | None = None,
        audio_duration_ms: int | None = None,
    ) -> MediaTicketBinding:
        current = _utc(now or datetime.now(UTC))
        expires = binding.expires_at
        if audio_duration_ms is not None:
            expires = min(
                expires,
                current + timedelta(milliseconds=max(0, audio_duration_ms)) + MEDIA_TICKET_GRACE,
            )
        with self._session() as session:
            session.execute(
                update(PlaybackMediaTicket)
                .where(PlaybackMediaTicket.token_hash == binding.token_hash)
                .values(started=True, expires_at=expires)
            )
        return MediaTicketBinding(
            token_hash=binding.token_hash,
            session_hash=binding.session_hash,
            controller_epoch=binding.controller_epoch,
            debate_id=binding.debate_id,
            turn_id=binding.turn_id,
            action=binding.action,
            control_version=binding.control_version,
            issued_at=binding.issued_at,
            expires_at=expires,
            started=True,
        )

    def revoke_token(self, token: str) -> None:
        self._delete(PlaybackMediaTicket.token_hash == self._hash(token))

    def revoke_epoch(self, controller_epoch: str) -> int:
        return self._delete(PlaybackMediaTicket.controller_epoch == controller_epoch)

    def revoke_item(self, debate_id: str, turn_id: str) -> int:
        return self._delete(
            PlaybackMediaTicket.debate_id == debate_id, PlaybackMediaTicket.turn_id == turn_id
        )

    def revoke_debate(self, debate_id: str) -> int:
        return self._delete(PlaybackMediaTicket.debate_id == debate_id)

    def _delete(self, *conditions: Any) -> int:
        with self._session() as session:
            result = session.execute(delete(PlaybackMediaTicket).where(*conditions))
            return int(getattr(result, "rowcount", 0) or 0)

    def active_count(self, *, now: datetime | None = None) -> int:
        """Unexpired tickets (tests and diagnostics)."""

        current = _utc(now or datetime.now(UTC))
        with self._session() as session:
            return len(
                session.scalars(
                    select(PlaybackMediaTicket.token_hash).where(
                        PlaybackMediaTicket.expires_at >= current
                    )
                ).all()
            )
