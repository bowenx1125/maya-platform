#!/usr/bin/env python3
"""Give existing Debates their own copy of each voice, for free (2026-10-24).

Dry-run by default (counts only). ``--apply`` copies, per voiced participant,
the source Voice's recording (when the Voice still has one) and its supplier
voice ID (from the Voice, or from the ID frozen into the participant). It is
idempotent and never enrolls or calls a supplier. Writing to the production
database also needs ``--confirm-production``.
"""

from __future__ import annotations

import argparse
import json
import os
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
    snapshot_debate_voices,
    source_voice_id,
)
from sqlalchemy import select  # noqa: E402


def plan(session: Any) -> dict[str, int]:
    counts = {"debates": 0, "voiced": 0, "has_copy": 0, "with_sample": 0, "id_only": 0}
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
                counts["has_copy"] += 1
                continue
            profile = session.get(VoiceProfile, voice)
            key = "with_sample" if profile is not None and profile.sample_file_id else "id_only"
            counts[key] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--data-root", default=None, type=Path)
    parser.add_argument("--apply", action="store_true", help="Write. Default is dry-run.")
    parser.add_argument("--confirm-production", action="store_true")
    args = parser.parse_args(argv)
    overrides: dict[str, Any] = {"maya_env": "operator"}
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if args.data_root is not None:
        overrides["data_root"] = args.data_root
    settings = Settings(_env_file=SCRIPT_ROOT / ".env", **overrides)
    lowered = f"{settings.database_url} {settings.resolved_data_root}".lower()
    production = (
        any(
            marker in lowered
            for marker in ("maya-production", "8.210.57.144", "/srv/maya-production")
        )
        or os.environ.get("MAYA_ENV") == "production"
    )
    if args.apply and production and not args.confirm_production:
        print("Production target: pass --confirm-production to write.", file=sys.stderr)
        return 2
    database = Database(settings.database_url)
    with database.session() as session:
        print(json.dumps({"before": plan(session)}, sort_keys=True))
        if args.apply:
            copied = 0
            for debate_id in session.scalars(select(Debate.id)).all():
                copied += len(
                    snapshot_debate_voices(
                        session,
                        debate_id,
                        participants_of(session, debate_id),
                        settings=settings,
                        origin="backfill",
                        data_root=settings.resolved_data_root,
                    )
                )
            session.commit()
            print(json.dumps({"copied": copied}, sort_keys=True))
        print(json.dumps({"after": plan(session)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
