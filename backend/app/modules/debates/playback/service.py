"""Teacher-controlled playback, composed from four responsibility modules.

The service was one 4,800-line class. It is now assembled from mixins that each
own one concern, so a change to turn preparation does not require reading the
media-command protocol:

- ``_core`` — state, persistence, queries, event staging
- ``_preparation`` — the generation fence, the provider call, the audio swap
- ``_control`` — the teacher's commands: start, next, pause, finish, reset
- ``_session`` — controller ownership, media commands, the public snapshot

The mixins all inherit ``PlaybackCore``, so the method resolution order is a
single line and every method still shares one ``self``, one lock and one
repository. This is a move, not a redesign: no behaviour changed.
"""

from __future__ import annotations

from ._control import PlaybackControlMixin
from ._core import (
    AudioAuthorization,
    ControllerHandle,
    EvidenceTraceCorruptError,
    PlaybackCore,
    PlaybackRuntime,
    PreparedMedia,
)
from ._preparation import PlaybackPreparationMixin
from ._session import PlaybackSessionMixin


class PlaybackService(
    PlaybackPreparationMixin,
    PlaybackControlMixin,
    PlaybackSessionMixin,
    PlaybackCore,
):
    """The teacher-controlled classroom stage."""


__all__ = [
    "AudioAuthorization",
    "ControllerHandle",
    "EvidenceTraceCorruptError",
    "PlaybackRuntime",
    "PlaybackService",
    "PreparedMedia",
]
