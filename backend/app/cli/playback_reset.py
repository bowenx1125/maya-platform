"""Explicit local operator reset for one stuck classroom playback.

This module is intentionally a CLI entry point, not a FastAPI router.  It
requires an exact Debate UUID and the literal ``--confirm RESET`` token so a
normal browser or an accidental invocation cannot reset classroom state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from app.core.config import get_settings
from app.core.db import Database
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.events import DebateEventHub
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlEventStore, SqlPlaybackRepository
from app.providers.factory import tts_provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reset one Maya debate playback state.")
    parser.add_argument("--debate-id", required=True, help="The exact Debate UUID to reset.")
    parser.add_argument(
        "--confirm",
        required=True,
        choices=("RESET",),
        help="Required explicit confirmation token: RESET.",
    )
    return parser


async def _run(debate_id: str) -> dict[str, object]:
    settings = get_settings()
    settings.validate_runtime()
    database = Database(settings.database_url, settings.resolved_data_root)
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    selected_tts = tts_provider(settings)
    service = PlaybackService(
        repository,
        audio_store=AudioStore(settings.resolved_data_root, tts_provider=selected_tts),
        event_hub=DebateEventHub(SqlEventStore(database.session_factory)),
        session_factory=database.session_factory,
        settings=settings,
        tts_provider=selected_tts,
    )
    try:
        with database.session() as db:
            debate = repository.get_debate(db, debate_id)
            if debate is None:
                raise RuntimeError("debate not found")
            expected_control_version = service._state(db, debate).control_version
            state = await service.operator_reset(
                db,
                debate_id,
                confirm=True,
                expected_control_version=expected_control_version,
                request_id=None,
            )
            return state.model_dump(mode="json")
    finally:
        database.dispose()


def main() -> None:
    args = _parser().parse_args()
    try:
        debate_id = str(UUID(args.debate_id))
    except ValueError as exc:
        _parser().error("--debate-id must be a valid UUID")
        raise AssertionError from exc
    print(json.dumps(asyncio.run(_run(debate_id)), sort_keys=True))


if __name__ == "__main__":
    main()
