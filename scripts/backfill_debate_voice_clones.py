#!/usr/bin/env python3
"""Give existing Debates their own provider voice clones (2026-10-20).

Default is a read-only dry run that prints counts only. ``--create-rows``
adds ``backfill`` clone rows (``pending`` when the platform Voice kept a
sample, otherwise ``no_sample``). ``--enroll`` creates the clones and calls
the configured provider; a real provider additionally needs ``--allow-real``.
Voices enrolled before 0077 kept no sample, so their Debates are counted as
``no_sample`` and keep using the platform Voice while it exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SCRIPT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.models import VoiceProfile  # noqa: E402
from app.modules.debates.models import Debate, DebateVoiceClone  # noqa: E402
from app.modules.debates.voice_clones import (  # noqa: E402
    participants_of,
    request_debate_clones,
    source_voice_id,
    sweep_debate_voice_clones,
)
from app.providers.factory import voice_provider  # noqa: E402
from sqlalchemy import select  # noqa: E402


def plan(session: Any) -> dict[str, int]:
    counts = {"debates": 0, "voiced": 0, "with_sample": 0, "no_sample": 0, "has_clone": 0}
    for debate_id in session.scalars(select(Debate.id)).all():
        counts["debates"] += 1
        for row in participants_of(session, debate_id):
            voice = source_voice_id(row)
            if voice is None:
                continue
            counts["voiced"] += 1
            if session.scalar(
                select(DebateVoiceClone.id).where(
                    DebateVoiceClone.debate_id == debate_id,
                    DebateVoiceClone.source_voice_profile_id == voice,
                )
            ):
                counts["has_clone"] += 1
                continue
            profile = session.get(VoiceProfile, voice)
            key = "with_sample" if profile is not None and profile.sample_file_id else "no_sample"
            counts[key] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--data-root", default=None, type=Path)
    parser.add_argument("--create-rows", action="store_true")
    parser.add_argument("--enroll", action="store_true")
    parser.add_argument("--allow-real", action="store_true")
    args = parser.parse_args(argv)
    overrides: dict[str, Any] = {"maya_env": "operator"}
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if args.data_root is not None:
        overrides["data_root"] = args.data_root
    settings = Settings(_env_file=SCRIPT_ROOT / ".env", **overrides)
    lowered = settings.database_url.lower()
    if "maya-production" in lowered or "8.210.57.144" in lowered:
        print("Refusing to touch a production database.", file=sys.stderr)
        return 2
    if args.enroll and settings.voice_provider != "mock" and not args.allow_real:
        print("Refusing to call a real voice provider without --allow-real.", file=sys.stderr)
        return 2
    database = Database(settings.database_url)
    with database.session() as session:
        print(json.dumps({"before": plan(session)}, sort_keys=True))
        if args.create_rows:
            for debate_id in session.scalars(select(Debate.id)).all():
                request_debate_clones(
                    session, debate_id, participants_of(session, debate_id), origin="backfill"
                )
            session.commit()
        if args.enroll:
            result = sweep_debate_voice_clones(
                session,
                data_root=settings.resolved_data_root,
                settings=settings,
                provider=voice_provider(settings),
                origin="backfill",
            )
            print(json.dumps({"enrolled": result}, sort_keys=True))
        print(json.dumps({"after": plan(session)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
