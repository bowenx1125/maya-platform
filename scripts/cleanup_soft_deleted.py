#!/usr/bin/env python3
"""Remove legacy hidden, soft-deleted and withdrawn rows. Dry-run by default.

Counts the rows before and after. Debate snapshots, Debate voice copies, grades and
Record answer payloads are never deleted; the write rolls back if their counts
move. Legacy soft-deleted Debates (nothing sets ``deleted_at`` any more) go
afterwards, one at a time, through the app's own Debate delete; the live
Debates' copies, Records and grades must not move. Old Agent versions are
pruned to the current version plus the previous AGENT.md. Files under the owned
storage roots that no row references, and that are older than an hour, are
listed and (with --apply) unlinked.

A production URL also needs --confirm-production next to --apply. Back up the
database and the data root first.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SCRIPT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.core.models import (  # noqa: E402
    Agent,
    KnowledgeDocument,
    KnowledgeSnapshot,
    StoredFile,
    VoiceProfile,
)
from app.modules.debates.models import Debate, DebateParticipant, PlaybackState  # noqa: E402
from app.modules.knowledge_sets.models import KnowledgeSet  # noqa: E402
from app.modules.learning.models import (  # noqa: E402
    AssessmentAttempt,
    AssessmentAttemptQuestion,
    LearningAssessment,
    LearningRecord,
)
from app.modules.real_delete import (  # noqa: E402
    hard_delete_agent,
    hard_delete_conversation,
    hard_delete_document,
    hard_delete_knowledge_set,
    hard_delete_team,
    hard_delete_voice,
    release_stored_file,
)
from app.modules.teams.models import Team  # noqa: E402
from app.modules.workspace.models import Conversation  # noqa: E402
from sqlalchemy import func, inspect, select, text  # noqa: E402


def _agent_in_live_team(session: Any, agent_id: str) -> bool:
    from app.modules.teams.models import TeamVersion, TeamVersionMember

    return (
        session.scalar(
            select(Team.id)
            .join(
                TeamVersion,
                (TeamVersion.team_id == Team.id)
                & (TeamVersion.version_seq == Team.current_version_seq),
            )
            .join(TeamVersionMember, TeamVersionMember.team_version_id == TeamVersion.id)
            .where(Team.deleted_at.is_(None), TeamVersionMember.agent_id == agent_id)
            .limit(1)
        )
        is not None
    )


def _looks_like_production(url: str, data_root: Path) -> bool:
    lowered = f"{url} {data_root}".lower()
    return (
        any(
            marker in lowered
            for marker in ("maya-production", "8.210.57.144", "/srv/maya-production")
        )
        or os.environ.get("MAYA_ENV") == "production"
    )


# Roots that only hold files a database row owns. Anything else under the
# data root (SQLite files, backups, Debate audio) is never scanned.
_OWNED_ROOTS = ("snapshots", "voice-samples", "debate-voice-samples")
_OWNED_GLOBS = ("groups/*/knowledge", "*/voices/previews", "*/*/voices/previews")
_ORPHAN_MIN_AGE_SECONDS = 3600


def _referenced_paths(session: Any) -> set[str]:
    from app.core.models import VoicePreview
    from app.modules.workspace.models import ConversationAttachment

    paths: set[str] = set(session.scalars(select(StoredFile.relative_path)).all())
    paths.update(session.scalars(select(VoicePreview.relative_path)).all())
    paths.update(session.scalars(select(ConversationAttachment.relative_path)).all())
    return {path.replace("\\", "/") for path in paths if path}


def disk_orphans(session: Any, data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    referenced = _referenced_paths(session)
    roots = [data_root / name for name in _OWNED_ROOTS]
    for pattern in _OWNED_GLOBS:
        roots.extend(data_root.glob(pattern))
    cutoff = time.time() - _ORPHAN_MIN_AGE_SECONDS
    found: list[Path] = []
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(data_root).as_posix()
            if relative in referenced or path.stat().st_mtime > cutoff:
                continue
            found.append(path)
    return sorted(found)


def _orphan_ids(session: Any) -> list[str]:
    """Stored files nothing references. Debate copies stay: their rows point at the file."""

    protected: set[str] = set()
    inspector = inspect(session.get_bind())
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get("referred_table") != "stored_files":
                continue
            for column_name in foreign_key.get("constrained_columns") or []:
                rows = session.execute(text(f'SELECT "{column_name}" FROM "{table_name}"'))
                protected.update(value for (value,) in rows if value)
    return [
        file_id
        for file_id in session.scalars(select(StoredFile.id)).all()
        if file_id not in protected
    ]


def counts(session: Any, data_root: Path) -> dict[str, int]:
    from app.core.models import AgentVersion

    debate_snapshots = session.scalar(
        select(func.count())
        .select_from(KnowledgeSnapshot)
        .where(KnowledgeSnapshot.owner_debate_id.is_not(None))
    )
    answer_rows = session.scalar(
        select(func.count())
        .select_from(AssessmentAttemptQuestion)
        .where(AssessmentAttemptQuestion.content_json.is_not(None))
    )
    return {
        "hidden_documents": int(
            session.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.workspace_state == "hidden")
            )
            or 0
        ),
        "deleted_voices": int(
            session.scalar(
                select(func.count())
                .select_from(VoiceProfile)
                .where(VoiceProfile.status == "deleted")
            )
            or 0
        ),
        "deleted_knowledge_sets": int(
            session.scalar(
                select(func.count())
                .select_from(KnowledgeSet)
                .where(KnowledgeSet.deleted_at.is_not(None))
            )
            or 0
        ),
        "deleted_agents": int(
            session.scalar(
                select(func.count()).select_from(Agent).where(Agent.deleted_at.is_not(None))
            )
            or 0
        ),
        "deleted_teams": int(
            session.scalar(
                select(func.count()).select_from(Team).where(Team.deleted_at.is_not(None))
            )
            or 0
        ),
        "withdrawn_chats": int(
            session.scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.withdrawn_at.is_not(None))
            )
            or 0
        ),
        "agent_versions": int(session.scalar(select(func.count()).select_from(AgentVersion)) or 0),
        "orphan_files": len(_orphan_ids(session)),
        "disk_orphan_files": len(disk_orphans(session, data_root)),
        "debate_snapshots": int(debate_snapshots or 0),
        "answer_payloads": int(answer_rows or 0),
        "debate_participants": int(
            session.scalar(select(func.count()).select_from(DebateParticipant)) or 0
        ),
        "records": int(session.scalar(select(func.count()).select_from(LearningRecord)) or 0),
        "attempts": int(session.scalar(select(func.count()).select_from(AssessmentAttempt)) or 0),
        "grades": int(session.scalar(select(func.count()).select_from(LearningAssessment)) or 0),
        "deleted_debates": int(
            session.scalar(
                select(func.count()).select_from(Debate).where(Debate.deleted_at.is_not(None))
            )
            or 0
        ),
        "agents_kept_for_live_teams": sum(
            1
            for agent_id in session.scalars(
                select(Agent.id).where(Agent.deleted_at.is_not(None))
            ).all()
            if _agent_in_live_team(session, agent_id)
        ),
    }


def live_debate_counts(session: Any) -> dict[str, int]:
    """What the Debate phase must not move: live Debates' copies, Records, grades."""

    live = select(Debate.id).where(Debate.deleted_at.is_(None))
    return {
        "snapshots": int(
            session.scalar(
                select(func.count())
                .select_from(KnowledgeSnapshot)
                .where(KnowledgeSnapshot.owner_debate_id.in_(live))
            )
            or 0
        ),
        "records": int(session.scalar(select(func.count()).select_from(LearningRecord)) or 0),
        "attempts": int(session.scalar(select(func.count()).select_from(AssessmentAttempt)) or 0),
        "grades": int(session.scalar(select(func.count()).select_from(LearningAssessment)) or 0),
        "participants": int(
            session.scalar(
                select(func.count())
                .select_from(DebateParticipant)
                .where(DebateParticipant.debate_id.in_(live))
            )
            or 0
        ),
    }


def delete_legacy_debates(database: Database, data_root: Path) -> tuple[int, int]:
    """Remove soft-deleted Debates with the teacher's Debate delete. Returns (done, failed)."""

    from app.modules.debates.cleanup import delete_all

    with database.session() as session:
        targets = [
            (str(row.id), str(row.created_by), int(row.revision))
            for row in session.scalars(select(Debate).where(Debate.deleted_at.is_not(None)))
        ]
    done = failed = 0
    for debate_id, actor_id, revision in targets:
        session = database.session_factory()
        try:
            playback = session.scalar(
                select(PlaybackState).where(PlaybackState.debate_id == debate_id)
            )
            if playback is None:
                raise RuntimeError("no playback state")
            asyncio.run(
                delete_all(
                    session,
                    actor_user_id=actor_id,
                    debate_id=debate_id,
                    expected_revision=revision,
                    expected_control_version=int(playback.control_version),
                    data_root=data_root,
                )
            )
            done += 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            failed += 1
            print("debate not removed", debate_id, type(exc).__name__)
        finally:
            session.close()
    return done, failed


def apply(session: Any, data_root: Path) -> None:
    for document in session.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.workspace_state == "hidden")
    ).all():
        hard_delete_document(session, document, data_root)
    for profile in session.scalars(
        select(VoiceProfile).where(VoiceProfile.status == "deleted")
    ).all():
        hard_delete_voice(session, profile, data_root)
    for row in session.scalars(
        select(KnowledgeSet).where(KnowledgeSet.deleted_at.is_not(None))
    ).all():
        hard_delete_knowledge_set(session, row, data_root)
    for agent in session.scalars(select(Agent).where(Agent.deleted_at.is_not(None))).all():
        # A Team still listing this Agent has to be edited first, same as the API.
        if _agent_in_live_team(session, agent.id):
            continue
        hard_delete_agent(session, agent, data_root)
    for team in session.scalars(select(Team).where(Team.deleted_at.is_not(None))).all():
        hard_delete_team(session, team)
    for chat in session.scalars(
        select(Conversation).where(Conversation.withdrawn_at.is_not(None))
    ).all():
        hard_delete_conversation(session, chat, data_root)
    from app.modules.real_delete import prune_agent_versions

    for agent_id in session.scalars(select(Agent.id)).all():
        prune_agent_versions(session, agent_id, data_root)
    for file_id in _orphan_ids(session):
        release_stored_file(session, data_root, file_id)
    session.flush()


def unlink_disk_orphans(session: Any, data_root: Path) -> int:
    removed = 0
    for path in disk_orphans(session, data_root):
        try:
            path.unlink()
            removed += 1
        except OSError:
            print("could not remove", path.relative_to(data_root).as_posix())
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--data-root", default=None, type=Path)
    parser.add_argument("--apply", action="store_true", help="Write. Default is dry-run.")
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required with --apply when the URL or data root is the production one.",
    )
    args = parser.parse_args(argv)
    overrides: dict[str, Any] = {"maya_env": "operator"}
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if args.data_root is not None:
        overrides["data_root"] = args.data_root
    settings = Settings(_env_file=SCRIPT_ROOT / ".env", **overrides)
    data_root = settings.resolved_data_root
    if (
        args.apply
        and _looks_like_production(settings.database_url, data_root)
        and not args.confirm_production
    ):
        raise SystemExit("Production target: pass --confirm-production with --apply.")
    database = Database(settings.database_url)
    with database.session() as session:
        before = counts(session, data_root)
        print("before", before)
        if not args.apply:
            for path in disk_orphans(session, data_root)[:50]:
                print("disk orphan", path.relative_to(data_root).as_posix())
            print("dry-run; pass --apply to write")
            return 0
        apply(session, data_root)
        after = counts(session, data_root)
        print("after", after)
        if after["debate_snapshots"] != before["debate_snapshots"]:
            session.rollback()
            raise SystemExit("Debate snapshots changed; the write was rolled back.")
        if after["answer_payloads"] != before["answer_payloads"]:
            session.rollback()
            raise SystemExit("Record answers changed; the write was rolled back.")
        if after["debate_participants"] != before["debate_participants"]:
            session.rollback()
            raise SystemExit("Debate participants changed; the write was rolled back.")
        for key in ("records", "attempts", "grades"):
            if after[key] != before[key]:
                session.rollback()
                raise SystemExit(f"{key} changed; the write was rolled back.")
        session.commit()
        live_before = live_debate_counts(session)
    done, failed = delete_legacy_debates(database, data_root)
    print("legacy debates removed", done, "failed", failed)
    with database.session() as session:
        if live_debate_counts(session) != live_before:
            raise SystemExit("Live Debates, Records or grades changed; stop and check.")
        print("disk orphan files removed", unlink_disk_orphans(session, data_root))
        print("final", counts(session, data_root))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
