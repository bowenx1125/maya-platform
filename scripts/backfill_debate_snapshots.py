#!/usr/bin/env python3
"""Copy AGENT.md, RAG/Knowledge and the voice into existing Debates.

Dry-run by default. ``--apply`` writes. The copy is idempotent: a Debate that
already owns its snapshot, markdown and voice row is left alone. The voice is
the source Voice's recording and supplier ID, copied for free: nothing is
enrolled and no supplier is called. Writing to the
production database also needs --confirm-production; back it up first.
"""

from __future__ import annotations

import argparse
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
from app.core.models import AgentVersion, KnowledgeSnapshot  # noqa: E402
from app.modules.debates.models import Debate, DebateVoiceClone  # noqa: E402
from app.modules.debates.owned_copies import adopt_debate_knowledge  # noqa: E402
from app.modules.debates.voice_clones import (  # noqa: E402
    participants_of,
    snapshot_debate_voices,
    source_voice_id,
)


def _guard_production(url: str, data_root: Path, *, apply: bool, confirmed: bool) -> None:
    lowered = f"{url} {data_root}".lower()
    production = (
        any(
            marker in lowered
            for marker in ("maya-production", "8.210.57.144", "/srv/maya-production")
        )
        or os.environ.get("MAYA_ENV") == "production"
    )
    if apply and production and not confirmed:
        raise SystemExit("Production target: pass --confirm-production with --apply.")


def plan(session: Any) -> dict[str, int]:
    counts = {
        "debates": 0,
        "missing_agent_md": 0,
        "unpinned_knowledge": 0,
        "missing_voice": 0,
    }
    for debate_id in session.scalars(select_ids(session)).all():
        counts["debates"] += 1
        for row in participants_of(session, debate_id):
            if not row.agent_md_snapshot and row.agent_version_id:
                counts["missing_agent_md"] += 1
            snapshot = (
                session.get(KnowledgeSnapshot, row.knowledge_snapshot_id)
                if row.knowledge_snapshot_id
                else None
            )
            if snapshot is not None and snapshot.owner_debate_id != debate_id:
                counts["unpinned_knowledge"] += 1
            voice = source_voice_id(row)
            if voice and session.scalar(select_clone(session, debate_id, voice)) is None:
                counts["missing_voice"] += 1
    return counts


def select_ids(session: Any) -> Any:
    from sqlalchemy import select

    return select(Debate.id)


def select_clone(session: Any, debate_id: str, voice_id: str) -> Any:
    from sqlalchemy import select

    return select(DebateVoiceClone.id).where(
        DebateVoiceClone.debate_id == debate_id,
        DebateVoiceClone.source_voice_profile_id == voice_id,
    )


def apply(session: Any, data_root: Path, settings: Any) -> dict[str, int]:
    filled = {"agent_md": 0, "knowledge": 0, "voice_rows": 0}
    from sqlalchemy import select

    for debate_id in session.scalars(select(Debate.id)).all():
        rows = participants_of(session, debate_id)
        for row in rows:
            if row.agent_md_snapshot or not row.agent_version_id:
                continue
            version = session.get(AgentVersion, row.agent_version_id)
            if version is None:
                continue
            row.agent_md_snapshot = version.agent_md
            row.persona_spec_hash_snapshot = version.persona_spec_hash
            filled["agent_md"] += 1
        before = {row.knowledge_snapshot_id for row in rows}
        adopt_debate_knowledge(session, debate_id, rows, data_root)
        session.flush()
        after = {row.knowledge_snapshot_id for row in rows}
        filled["knowledge"] += len(after - before)
        created = snapshot_debate_voices(
            session, debate_id, rows, settings=settings, origin="backfill", data_root=data_root
        )
        filled["voice_rows"] += len(created)
    session.commit()
    return filled


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
    _guard_production(
        settings.database_url,
        settings.resolved_data_root,
        apply=args.apply,
        confirmed=args.confirm_production,
    )
    database = Database(settings.database_url)
    with database.session() as session:
        before = plan(session)
        print("before", before)
        if not args.apply:
            print("dry-run; pass --apply to write")
            return 0
        written = apply(session, settings.resolved_data_root, settings)
        after = plan(session)
        print("wrote", written)
        print("after", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
