"""Sequential, resumable backfill of derived cards at current published versions."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, deque
from collections.abc import Callable

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.models import Agent, AgentDebateCard, AgentVersion, ProviderOperation
from app.modules.agents.debate_cards import ensure_agent_card
from app.modules.agents.markdown import markdown_hash

PROVIDER_FAILURES = frozenset(
    {
        "debate_card_acceptance_unknown",
        "debate_card_transport_failed",
        "debate_card_http_rejected",
        "debate_card_not_sent",
    }
)


def backfill(
    database: Database,
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> Counter[str]:
    counts: Counter[str] = Counter({"ready": 0, "salvaged": 0, "fallback": 0})
    recent: deque[bool] = deque(maxlen=20)
    consecutive = 0
    started = time.monotonic()
    with database.session() as db:
        ids = list(
            db.scalars(select(Agent.id).where(Agent.deleted_at.is_(None)).order_by(Agent.id))
        )
    for agent_id in ids:
        if limit is not None and counts["attempted"] >= limit:
            break
        with database.session() as db:
            agent = db.get(Agent, agent_id)
            if agent is None or agent.deleted_at is not None:
                continue
            version = (
                db.get(AgentVersion, agent.current_published_version_id)
                if agent.current_published_version_id
                else None
            )
            if version is None or version.agent_id != agent_id or version.state != "published":
                counts["unpublished"] += 1
                continue
            row = db.get(AgentDebateCard, agent_id)
            if row is not None and row.agent_md_hash == markdown_hash(version.agent_md):
                counts["skipped"] += 1
                continue
            counts["attempted"] += 1
            if dry_run:
                counts["would_compile"] += 1
                continue
            # IDs and the explicit operator-requested name only; no source text.
            name = agent.name
            row = ensure_agent_card(db, agent_id, settings, published_only=True, wait=True)
            if row is None:
                counts["unpublished"] += 1
                continue
            code = row.card_safe_error_code
            counts[row.card_status] += 1
            if row.salvaged:
                counts["salvaged"] += 1
            if code:
                counts[code] += 1
                emit(
                    json.dumps(
                        {"agent_id": agent_id, "name": name, "reason": code}, ensure_ascii=False
                    )
                )
            operations = db.scalars(
                select(ProviderOperation).where(
                    ProviderOperation.scope_id == f"agent_card:{agent_id}"
                )
            )
            counts["charged_requests_in_visited_scopes"] += sum(
                op.charged_request_count for op in operations
            )
            failed = code in PROVIDER_FAILURES
            recent.append(failed)
            consecutive = consecutive + 1 if failed else 0
            if consecutive >= 5 or (len(recent) == 20 and sum(recent) / 20 > 0.30):
                counts["spike_stopped"] = 1
                break
        if not dry_run:
            sleep(2.5)
    emit(
        json.dumps(
            {
                "counts": dict(counts),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "actual_tokens": None,
                "actual_cost_cny": None,
            },
            sort_keys=True,
        )
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        counts = backfill(database, settings, dry_run=args.dry_run, limit=args.limit)
    finally:
        database.dispose()
    if counts["spike_stopped"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
