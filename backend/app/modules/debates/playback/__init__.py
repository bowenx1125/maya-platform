"""Teacher-controlled playback for the Wave 2 classroom stage.

The playback package deliberately owns only the presentation boundary.  Debate
setup and turn generation are injected through small protocols so the module
does not import, or silently grow, the M10/M11 domain models.
"""

from .audio import AudioStore, MediaTicketStore
from .events import DebateEventHub, event_to_wire
from .service import PlaybackService

__all__ = [
    "AudioStore",
    "DebateEventHub",
    "MediaTicketStore",
    "PlaybackService",
    "event_to_wire",
]
