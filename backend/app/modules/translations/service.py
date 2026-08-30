"""M15 translation batches, immutable cache and history read projections.

This service intentionally uses a narrow SQL boundary for the Wave 3 tables.
M13/M14 own their ORM models and migration registration in parallel; keeping
the queries scoped by ``debate_id`` lets the three modules merge without
creating cross-module mapper relationships.  Every writer opens a short
``BEGIN IMMEDIATE`` transaction and no asynchronous task owns a socket or a
request SQLAlchemy Session.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.errors import (
    PlatformError,
    forbidden,
    invalid_state,
    not_found,
    unprocessable,
)
from app.core.models import IdempotencyRecord
from app.modules.auth.service import AuthContext
from app.modules.debates.playback.eligibility import has_complete_finished_playback
from app.modules.knowledge.services import (
    abandon_idempotency,
    claim_idempotency,
    finish_idempotency,
)

from .manifest import (
    MOCK_POLICY_KEY,
    MOCK_QUALITY_KEY,
    TARGET_LANGUAGE,
    ManifestSource,
    TranslationInputManifestV1,
    canonical_json_bytes,
    collect_manifest_sources,
    source_text_hash,
)
from .policy import (
    TranslationInput,
    TranslationOutput,
    TranslationProvider,
    translation_provider,
)
from .schemas import (
    TranslationBatchDTO,
    TranslationBatchStatus,
    TranslationItemStatus,
    TranslationItemSummary,
)

TRANSLATION_JOB_OPERATION = "translation.generate"
TRANSLATION_OPERATION = TRANSLATION_JOB_OPERATION
OPERATION_INTERRUPTED = "operation_interrupted"
SOURCE_CHANGED = "translation_source_changed"
SOURCE_UNAVAILABLE = "translation_source_unavailable"
PROVIDER_FAILED = "translation_provider_failed"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return _now()


def _json(value: Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def _begin_immediate(db: Session) -> None:
    """Start the required first-statement SQLite writer transaction."""

    db.rollback()
    bind = db.get_bind()
    if getattr(bind.dialect, "name", None) == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
    else:  # pragma: no cover - Maya's production boundary is SQLite.
        db.begin()


def _table_columns(db: Session, table: str) -> set[str]:
    """Return known columns without interpolating arbitrary identifiers."""

    allowed = {
        "translation_batches",
        "translation_entries",
        "translation_batch_items",
        "jobs",
        "civilization_report_current_success",
        "civilization_report_revisions",
    }
    if table not in allowed:
        raise ValueError("unexpected M15 table")
    try:
        rows = db.execute(text(f"PRAGMA table_info({table})")).all()
    except (OperationalError, OSError):
        return set()
    return {str(row[1]) for row in rows}


def _quality_column(db: Session, table: str) -> str:
    columns = _table_columns(db, table)
    if "quality_key" in columns:
        return "quality_key"
    if "quality" in columns:
        return "quality"
    # A missing column means the migration is not installed. Keep the error
    # explicit rather than silently dropping policy/quality cache identity.
    raise invalid_state("Wave 3 translation schema is not installed.")


def _has_table(db: Session, table: str) -> bool:
    try:
        return bool(
            db.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table},
            ).first()
        )
    except OperationalError:
        return False


def _uuid(value: Any) -> UUID:
    return UUID(str(value))


def _require_teacher(db: Session, actor_user_id: str, debate_id: str) -> str:
    """Resolve the course and enforce existing teacher visibility semantics."""

    row = db.execute(
        text(
            "SELECT d.course_id, d.status, cm.role FROM debates d "
            "LEFT JOIN course_members cm ON cm.course_id=d.course_id "
            "AND cm.user_id=:user_id WHERE d.id=:debate_id"
        ),
        {"user_id": actor_user_id, "debate_id": debate_id},
    ).first()
    if row is None:
        raise not_found()
    course_id, debate_status, role = str(row[0]), str(row[1]), row[2]
    if role is None:
        raise not_found()
    if role != "teacher":
        raise forbidden()
    if debate_status == "stopped" or (
        debate_status in {"debate_finished", "completed"}
        and not has_complete_finished_playback(db, debate_id)
    ):
        raise not_found()
    return course_id


def _parse_manifest(value: str) -> TranslationInputManifestV1:
    try:
        parsed = json.loads(value)
        return TranslationInputManifestV1.model_validate(parsed)
    except (TypeError, ValueError) as exc:
        raise invalid_state("The translation input manifest is invalid.") from exc


@dataclass(frozen=True, slots=True)
class TranslationEventPayload:
    """Summary-only event payload for the main event hub integration."""

    batch_id: str
    status: str
    total_items: int
    succeeded_items: int
    failed_items: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "total_items": self.total_items,
            "succeeded_items": self.succeeded_items,
            "failed_items": self.failed_items,
        }


class TranslationTaskManager:
    """Bounded single-process scheduler for pending translation Jobs."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def active_batch_ids(self) -> tuple[str, ...]:
        return tuple(self._tasks)

    async def enqueue(self, service: TranslationService, batch_id: str) -> bool:
        if self._closed:
            return False
        async with self._lock:
            previous = self._tasks.get(batch_id)
            if previous is not None and not previous.done():
                return False
            task = asyncio.create_task(
                self._run(service, batch_id), name=f"maya-translation-{batch_id}"
            )
            self._tasks[batch_id] = task
            return True

    async def _run(self, service: TranslationService, batch_id: str) -> None:
        try:
            await service.run_batch_async(batch_id)
        except asyncio.CancelledError:
            raise
        finally:
            async with self._lock:
                current = self._tasks.get(batch_id)
                if current is asyncio.current_task():
                    self._tasks.pop(batch_id, None)

    async def wait_batch(self, batch_id: str) -> None:
        while True:
            async with self._lock:
                task = self._tasks.get(batch_id)
            if task is None:
                return
            await asyncio.gather(task, return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._tasks.clear()


class TranslationService:
    """Teacher-triggered batches over immutable English history."""

    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
        *,
        settings: object | None = None,
        provider: TranslationProvider | None = None,
        task_manager: TranslationTaskManager | None = None,
        event_publisher: Callable[[str, str, Mapping[str, Any]], Any] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.provider = provider or translation_provider(settings)
        self.task_manager = task_manager or TranslationTaskManager()
        self.event_publisher = event_publisher

    def _session(self) -> Session:
        if self.session_factory is None:
            raise RuntimeError("TranslationService requires a session factory")
        return self.session_factory()

    def collect_manifest(
        self,
        db: Session,
        debate_id: str,
    ) -> tuple[TranslationInputManifestV1, tuple[ManifestSource, ...]]:
        return collect_manifest_sources(
            db,
            debate_id,
            target_language=TARGET_LANGUAGE,
            policy_key=MOCK_POLICY_KEY,
            quality_key=MOCK_QUALITY_KEY,
        )

    def list_batches(
        self,
        db: Session,
        *,
        actor_user_id: str,
        debate_id: str,
    ) -> list[TranslationBatchDTO]:
        _require_teacher(db, actor_user_id, debate_id)
        if not _has_table(db, "translation_batches"):
            return []
        rows = db.execute(
            text(
                "SELECT id FROM translation_batches WHERE debate_id=:debate_id "
                "ORDER BY created_at DESC, id DESC"
            ),
            {"debate_id": debate_id},
        ).all()
        return [self.get_batch(db, batch_id=str(row[0])) for row in rows]

    def get_batch(self, db: Session, *, batch_id: str) -> TranslationBatchDTO:
        quality = _quality_column(db, "translation_batches")
        row = (
            db.execute(
                text(
                    "SELECT id, debate_id, input_hash, status, target_language, "
                    f"{quality} AS quality_value, total_items, succeeded_items, failed_items, "
                    "created_at, updated_at FROM translation_batches WHERE id=:id"
                ),
                {"id": batch_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise not_found()
        entry_quality = _quality_column(db, "translation_entries")
        item_rows = (
            db.execute(
                text(
                    "SELECT i.order_index, i.status, i.reused, i.safe_error_code, "
                    "e.content_type, e.turn_id, e.report_revision_id, e.source_text_hash "
                    "FROM translation_batch_items i JOIN translation_entries e "
                    "ON e.id=i.entry_id AND e.debate_id=i.debate_id "
                    "WHERE i.batch_id=:batch_id ORDER BY i.order_index"
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .all()
        )
        del entry_quality
        items: list[TranslationItemSummary] = []
        for item in item_rows:
            content_id = item["turn_id"] or item["report_revision_id"]
            if content_id is None:
                raise invalid_state("A translation item has no content identity.")
            items.append(
                TranslationItemSummary(
                    content_type=cast(
                        Literal["turn", "report_revision"],
                        str(item["content_type"]),
                    ),
                    content_id=_uuid(content_id),
                    source_text_hash=str(item["source_text_hash"]),
                    status=cast(TranslationItemStatus, str(item["status"])),
                    reused=bool(item["reused"]),
                    safe_error_code=item["safe_error_code"],
                )
            )
        return TranslationBatchDTO(
            id=_uuid(row["id"]),
            debate_id=_uuid(row["debate_id"]),
            input_hash=str(row["input_hash"]),
            status=cast(TranslationBatchStatus, str(row["status"])),
            target_language=cast(Literal["zh-Hans"], TARGET_LANGUAGE),
            quality=cast(Literal["test_representation"], MOCK_QUALITY_KEY),
            total_items=int(row["total_items"]),
            succeeded_items=int(row["succeeded_items"]),
            failed_items=int(row["failed_items"]),
            items=items,
            created_at=_iso(row["created_at"]),
            updated_at=_iso(row["updated_at"]),
        )

    def request_translation(
        self,
        db: Session,
        *,
        actor_user_id: str,
        debate_id: str,
        idempotency_key: str,
        context: AuthContext | None = None,
        schedule: bool = False,
    ) -> TranslationBatchDTO | Any:
        """Create/reuse one batch and optionally schedule its Job.

        Manifest construction and the zero-content rejection happen before
        the user-bound idempotency claim.  Therefore a no-content 422 leaves
        no idempotency record, matching the frozen contract.
        """

        course_id = _require_teacher(db, actor_user_id, debate_id)
        manifest, sources = self.collect_manifest(db, debate_id)
        if manifest.item_count == 0:
            raise unprocessable(
                "no_translatable_content",
                "No public finalized English content is available for translation.",
            )
        body_hash = manifest.input_hash
        # Generic idempotency records are only for authenticated teacher
        # commands. Their response remains token-free and can be replayed.
        pseudo_context = context or _context_for_user(db, actor_user_id)
        record, replay = claim_idempotency(
            db,
            pseudo_context,
            TRANSLATION_OPERATION,
            idempotency_key,
            body_hash,
        )
        if replay is not None:
            return replay
        try:
            _begin_immediate(db)
            quality_batch = _quality_column(db, "translation_batches")
            active = db.execute(
                text(
                    "SELECT id FROM translation_batches WHERE debate_id=:debate_id "
                    "AND input_hash=:input_hash AND target_language=:target_language "
                    "AND status IN ('pending','running') ORDER BY created_at LIMIT 1"
                ),
                {
                    "debate_id": debate_id,
                    "input_hash": manifest.input_hash,
                    "target_language": TARGET_LANGUAGE,
                },
            ).first()
            if active is not None:
                batch_id = str(active[0])
                result = self.get_batch(db, batch_id=batch_id)
                finish_idempotency(db, record, 202, result.model_dump(mode="json"))
                db.commit()
                if schedule:
                    self._schedule_if_needed(batch_id)
                return result

            batch_id = str(uuid4())
            now = _now()
            db.execute(
                text(
                    "INSERT INTO translation_batches "
                    "(id, debate_id, course_id, requested_by, target_language, policy_key, "
                    f"{quality_batch}, status, manifest_json, input_hash, total_items, "
                    "succeeded_items, failed_items, created_at, updated_at) VALUES "
                    "(:id, :debate_id, :course_id, :requested_by, :target_language, "
                    f":policy_key, :quality_value, :status, :manifest_json, :input_hash, "
                    ":total_items, :succeeded_items, :failed_items, :created_at, :updated_at)"
                ),
                {
                    "id": batch_id,
                    "debate_id": debate_id,
                    "course_id": course_id,
                    "requested_by": actor_user_id,
                    "target_language": TARGET_LANGUAGE,
                    "policy_key": manifest.policy_key,
                    "quality_value": manifest.quality_key,
                    "status": "pending",
                    "manifest_json": _json(manifest.canonical_dict()),
                    "input_hash": manifest.input_hash,
                    "total_items": manifest.item_count,
                    "succeeded_items": 0,
                    "failed_items": 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )

            all_ready = True
            for order_index, source in enumerate(sources):
                existing = self._cache_entry(
                    db,
                    debate_id=debate_id,
                    source=source,
                    policy_key=manifest.policy_key,
                    quality_key=manifest.quality_key,
                )
                if existing is None:
                    all_ready = False
                    entry_id = str(uuid4())
                    self._insert_entry(
                        db,
                        entry_id=entry_id,
                        debate_id=debate_id,
                        source=source,
                        policy_key=manifest.policy_key,
                        quality_key=manifest.quality_key,
                        now=now,
                    )
                    item_status = "pending"
                    reused = False
                else:
                    entry_id, entry_status = existing
                    item_status = "ready" if entry_status == "ready" else "pending"
                    reused = True
                    if item_status != "ready":
                        all_ready = False
                self._insert_batch_item(
                    db,
                    batch_id=batch_id,
                    entry_id=entry_id,
                    debate_id=debate_id,
                    order_index=order_index,
                    reused=reused,
                    status=item_status,
                )

            if all_ready:
                self._set_batch_counts(db, batch_id, status="completed", now=now)
            else:
                self._insert_translation_job(db, batch_id=batch_id, debate_id=debate_id, now=now)
            result = self.get_batch(db, batch_id=batch_id)
            finish_idempotency(db, record, 202, result.model_dump(mode="json"))
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # A competing different-key request may win the unique active
            # fence. Reuse that durable batch; never generate twice.
            active_row = db.execute(
                text(
                    "SELECT id FROM translation_batches WHERE debate_id=:debate_id "
                    "AND input_hash=:input_hash AND target_language=:target_language "
                    "AND status IN ('pending','running') ORDER BY created_at LIMIT 1"
                ),
                {
                    "debate_id": debate_id,
                    "input_hash": manifest.input_hash,
                    "target_language": TARGET_LANGUAGE,
                },
            ).first()
            if active_row is None:
                _abandon_claim_safely(db, record)
                raise invalid_state("The translation batch could not be created.") from exc
            result = self.get_batch(db, batch_id=str(active_row[0]))
            finish_idempotency(db, record, 202, result.model_dump(mode="json"))
            db.commit()
            batch_id = str(active_row[0])
        except Exception:
            db.rollback()
            _abandon_claim_safely(db, record)
            raise

        if result.status == "completed":
            self._publish_event("translation.batch_completed", result)
        if schedule and result.status in {"pending", "running"}:
            self._schedule_if_needed(batch_id)
        return result

    def _schedule_if_needed(self, batch_id: str) -> None:
        """Schedule through a running event loop, otherwise leave Job pending."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.task_manager.enqueue(self, batch_id))

    def _publish_event(self, event_type: str, result: TranslationBatchDTO) -> None:
        if self.event_publisher is None:
            return
        self.event_publisher(
            str(result.debate_id),
            event_type,
            TranslationEventPayload(
                str(result.id),
                result.status,
                result.total_items,
                result.succeeded_items,
                result.failed_items,
            ).as_dict(),
        )

    def _cache_entry(
        self,
        db: Session,
        *,
        debate_id: str,
        source: ManifestSource,
        policy_key: str,
        quality_key: str,
    ) -> tuple[str, str] | None:
        quality = _quality_column(db, "translation_entries")
        identity_column = "turn_id" if source.content_type == "turn" else "report_revision_id"
        other_column = "report_revision_id" if source.content_type == "turn" else "turn_id"
        row = db.execute(
            text(
                "SELECT id, status FROM translation_entries WHERE debate_id=:debate_id "
                "AND content_type=:content_type AND "
                f"{identity_column}=:content_id AND {other_column} IS NULL "
                "AND source_text_hash=:source_text_hash AND target_language=:target_language "
                f"AND policy_key=:policy_key AND {quality}=:quality_value "
                "AND status IN ('ready','pending','running') "
                "ORDER BY CASE status WHEN 'ready' THEN 0 WHEN 'running' THEN 1 ELSE 2 END, "
                "created_at, id LIMIT 1"
            ),
            {
                "debate_id": debate_id,
                "content_type": source.content_type,
                "content_id": source.content_id,
                "source_text_hash": source.source_text_hash,
                "target_language": TARGET_LANGUAGE,
                "policy_key": policy_key,
                "quality_value": quality_key,
            },
        ).first()
        return (str(row[0]), str(row[1])) if row is not None else None

    def _insert_entry(
        self,
        db: Session,
        *,
        entry_id: str,
        debate_id: str,
        source: ManifestSource,
        policy_key: str,
        quality_key: str,
        now: datetime,
    ) -> None:
        quality = _quality_column(db, "translation_entries")
        turn_id = source.content_id if source.content_type == "turn" else None
        report_id = source.content_id if source.content_type == "report_revision" else None
        db.execute(
            text(
                "INSERT INTO translation_entries "
                "(id, debate_id, content_type, turn_id, report_revision_id, source_text_hash, "
                "target_language, policy_key, "
                f"{quality}, status, translated_text, safe_error_code, created_at, updated_at) "
                "VALUES (:id, :debate_id, :content_type, :turn_id, :report_revision_id, "
                ":source_text_hash, :target_language, :policy_key, :quality_value, "
                ":status, NULL, NULL, :created_at, :updated_at)"
            ),
            {
                "id": entry_id,
                "debate_id": debate_id,
                "content_type": source.content_type,
                "turn_id": turn_id,
                "report_revision_id": report_id,
                "source_text_hash": source.source_text_hash,
                "target_language": TARGET_LANGUAGE,
                "policy_key": policy_key,
                "quality_value": quality_key,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
        )

    def _insert_batch_item(
        self,
        db: Session,
        *,
        batch_id: str,
        entry_id: str,
        debate_id: str,
        order_index: int,
        reused: bool,
        status: str,
    ) -> None:
        db.execute(
            text(
                "INSERT INTO translation_batch_items "
                "(batch_id, entry_id, debate_id, order_index, reused, status, safe_error_code) "
                "VALUES (:batch_id, :entry_id, :debate_id, :order_index, :reused, "
                ":status, NULL)"
            ),
            {
                "batch_id": batch_id,
                "entry_id": entry_id,
                "debate_id": debate_id,
                "order_index": order_index,
                "reused": reused,
                "status": status,
            },
        )

    def _insert_translation_job(
        self,
        db: Session,
        *,
        batch_id: str,
        debate_id: str,
        now: datetime,
    ) -> None:
        columns = _table_columns(db, "jobs")
        if "translation_batch_id" not in columns:
            # Isolated pre-0007 tests can execute the service synchronously;
            # production integration must install the typed owner column.
            return
        values: dict[str, Any] = {
            "id": str(uuid4()),
            "document_id": None,
            "debate_id": debate_id,
            "turn_id": None,
            "idempotency_key": None,
            "claim_token": None,
            "cancellation_generation": None,
            "operation": TRANSLATION_JOB_OPERATION,
            "state": "pending",
            "safe_error_code": None,
            "attempt": 0,
            "created_at": now,
            "updated_at": now,
            "translation_batch_id": batch_id,
        }
        job_columns = [name for name in values if name in columns]
        names = ", ".join(job_columns)
        params = ", ".join(f":{name}" for name in job_columns)
        db.execute(text(f"INSERT INTO jobs ({names}) VALUES ({params})"), values)

    def _set_batch_counts(self, db: Session, batch_id: str, *, status: str, now: datetime) -> None:
        counts = Counter(
            str(row[0])
            for row in db.execute(
                text("SELECT status FROM translation_batch_items WHERE batch_id=:batch_id"),
                {"batch_id": batch_id},
            ).all()
        )
        total = sum(counts.values())
        succeeded = counts["ready"]
        failed = counts["failed"]
        if status in {"completed", "partial", "failed"} and total != succeeded + failed:
            raise invalid_state("A terminal translation batch has nonterminal items.")
        db.execute(
            text(
                "UPDATE translation_batches SET status=:status, total_items=:total_items, "
                "succeeded_items=:succeeded_items, failed_items=:failed_items, "
                "updated_at=:updated_at WHERE id=:batch_id"
            ),
            {
                "status": status,
                "total_items": total,
                "succeeded_items": succeeded,
                "failed_items": failed,
                "updated_at": now,
                "batch_id": batch_id,
            },
        )

    def _claim_batch(self, db: Session, batch_id: str) -> bool:
        """Claim the typed Job and transition batch/items in one writer tx."""

        _begin_immediate(db)
        batch = (
            db.execute(
                text(
                    "SELECT id, debate_id, status, manifest_json, input_hash, target_language, "
                    "policy_key FROM translation_batches WHERE id=:batch_id"
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .first()
        )
        if batch is None:
            db.rollback()
            return False
        if str(batch["status"]) in {"completed", "partial", "failed"}:
            db.rollback()
            return False
        try:
            self._validate_batch_contract(db, batch)
        except PlatformError:
            db.rollback()
            self._mark_batch_failed(batch_id, "translation_contract_invalid")
            return False
        columns = _table_columns(db, "jobs")
        if "translation_batch_id" not in columns:
            db.rollback()
            self._mark_batch_failed(batch_id, "translation_job_owner_invalid")
            return False
        jobs = (
            db.execute(
                text(
                    "SELECT id, operation, state FROM jobs "
                    "WHERE translation_batch_id=:batch_id ORDER BY created_at, id"
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .all()
        )
        if (
            len(jobs) != 1
            or str(jobs[0]["operation"]) != TRANSLATION_JOB_OPERATION
            or str(jobs[0]["state"]) != "pending"
        ):
            db.rollback()
            self._mark_batch_failed(batch_id, "translation_job_owner_invalid")
            return False
        job_changed = db.execute(
            text(
                "UPDATE jobs SET state='running', attempt=attempt+1, updated_at=:updated_at "
                "WHERE id=:id AND translation_batch_id=:batch_id "
                "AND operation=:operation AND state='pending'"
            ),
            {
                "updated_at": _now(),
                "id": str(jobs[0]["id"]),
                "batch_id": batch_id,
                "operation": TRANSLATION_JOB_OPERATION,
            },
        )
        if getattr(job_changed, "rowcount", 0) != 1:
            db.rollback()
            return False
        batch_changed = db.execute(
            text(
                "UPDATE translation_batches SET status='running', updated_at=:updated_at "
                "WHERE id=:batch_id AND status='pending'"
            ),
            {"updated_at": _now(), "batch_id": batch_id},
        )
        if getattr(batch_changed, "rowcount", 0) != 1:
            db.rollback()
            return False
        pending_items = db.execute(
            text(
                "SELECT entry_id, reused FROM translation_batch_items WHERE batch_id=:batch_id "
                "AND status='pending' ORDER BY order_index"
            ),
            {"batch_id": batch_id},
        ).all()
        for item in pending_items:
            entry_id = str(item[0])
            reused = bool(item[1])
            if reused:
                entry_status = db.execute(
                    text("SELECT status FROM translation_entries WHERE id=:entry_id"),
                    {"entry_id": entry_id},
                ).scalar_one_or_none()
                if entry_status == "ready":
                    db.execute(
                        text(
                            "UPDATE translation_batch_items SET status='ready', "
                            "safe_error_code=NULL WHERE batch_id=:batch_id "
                            "AND entry_id=:entry_id AND status='pending'"
                        ),
                        {"batch_id": batch_id, "entry_id": entry_id},
                    )
                # A reused pending/running entry is owned by another batch.
                # It remains pending here and is retried after that owner
                # publishes the immutable ready cache entry.
                continue
            claimed = db.execute(
                text(
                    "UPDATE translation_entries SET status='running', updated_at=:updated_at "
                    "WHERE id=:entry_id AND status='pending'"
                ),
                {"updated_at": _now(), "entry_id": entry_id},
            )
            if getattr(claimed, "rowcount", 0) == 1:
                db.execute(
                    text(
                        "UPDATE translation_batch_items SET status='running' "
                        "WHERE batch_id=:batch_id AND entry_id=:entry_id AND status='pending'"
                    ),
                    {"batch_id": batch_id, "entry_id": entry_id},
                )
                continue
            entry_status = db.execute(
                text("SELECT status FROM translation_entries WHERE id=:entry_id"),
                {"entry_id": entry_id},
            ).scalar_one_or_none()
            next_status = "ready" if entry_status == "ready" else "failed"
            db.execute(
                text(
                    "UPDATE translation_batch_items SET status=:status, safe_error_code=:code "
                    "WHERE batch_id=:batch_id AND entry_id=:entry_id AND status='pending'"
                ),
                {
                    "status": next_status,
                    "code": None if next_status == "ready" else "translation_entry_active",
                    "batch_id": batch_id,
                    "entry_id": entry_id,
                },
            )
        db.commit()
        return True

    def _validate_batch_contract(self, db: Session, batch: Any) -> None:
        """Validate the immutable manifest and every ordered cache identity."""

        manifest = _parse_manifest(str(batch["manifest_json"]))
        canonical = _json(manifest.canonical_dict())
        if (
            str(batch["manifest_json"]) != canonical
            or str(batch["input_hash"]) != manifest.input_hash
            or str(batch["debate_id"]) != str(manifest.debate_id)
            or str(batch["target_language"]) != manifest.target_language
            or str(batch["policy_key"]) != manifest.policy_key
        ):
            raise invalid_state("The translation batch manifest identity is invalid.")
        quality = _quality_column(db, "translation_batches")
        entry_quality = _quality_column(db, "translation_entries")
        batch_quality = db.execute(
            text(f"SELECT {quality} FROM translation_batches WHERE id=:id"),
            {"id": str(batch["id"])},
        ).scalar_one()
        if str(batch_quality) != manifest.quality_key:
            raise invalid_state("The translation batch quality identity is invalid.")
        expected: list[tuple[int, str, str, str]] = [
            (index, "turn", str(turn.turn_id), turn.source_text_hash)
            for index, turn in enumerate(
                sorted(manifest.turns, key=lambda item: (item.turn_index, str(item.turn_id)))
            )
        ]
        if manifest.report is not None:
            expected.append(
                (
                    len(expected),
                    "report_revision",
                    str(manifest.report.report_revision_id),
                    manifest.report.source_text_hash,
                )
            )
        rows = (
            db.execute(
                text(
                    "SELECT i.order_index, i.debate_id, e.content_type, e.turn_id, "
                    "e.report_revision_id, e.source_text_hash, e.target_language, e.policy_key, "
                    f"e.{entry_quality} AS quality_value FROM translation_batch_items i "
                    "JOIN translation_entries e ON e.id=i.entry_id AND e.debate_id=i.debate_id "
                    "WHERE i.batch_id=:batch_id ORDER BY i.order_index"
                ),
                {"batch_id": str(batch["id"])},
            )
            .mappings()
            .all()
        )
        actual = [
            (
                int(row["order_index"]),
                str(row["content_type"]),
                str(row["turn_id"] or row["report_revision_id"]),
                str(row["source_text_hash"]),
            )
            for row in rows
        ]
        if actual != expected or any(
            str(row["debate_id"]) != str(manifest.debate_id)
            or str(row["target_language"]) != manifest.target_language
            or str(row["policy_key"]) != manifest.policy_key
            or str(row["quality_value"]) != manifest.quality_key
            for row in rows
        ):
            raise invalid_state("The translation batch item identity is invalid.")

    def run_batch(self, batch_id: str) -> TranslationBatchDTO | None:
        """Run one claimed batch synchronously (used by worker and tests)."""

        if self.session_factory is None:
            raise RuntimeError("TranslationService requires a session factory")
        claim_session = self._session()
        try:
            if not self._claim_batch(claim_session, batch_id):
                return self._safe_get_batch(batch_id)
        finally:
            claim_session.close()

        db = self._session()
        result: TranslationBatchDTO | None = None
        try:
            batch_contract = (
                db.execute(
                    text(
                        "SELECT id, debate_id, status, manifest_json, input_hash, target_language, "
                        "policy_key FROM translation_batches WHERE id=:batch_id "
                        "AND status='running'"
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .first()
            )
            if batch_contract is None:
                raise invalid_state("The translation batch claim is no longer valid.")
            self._validate_batch_contract(db, batch_contract)
            rows = (
                db.execute(
                    text(
                        "SELECT i.entry_id, i.status, i.debate_id, e.content_type, e.turn_id, "
                        "e.report_revision_id, e.source_text_hash FROM translation_batch_items i "
                        "JOIN translation_entries e ON e.id=i.entry_id AND e.debate_id=i.debate_id "
                        "WHERE i.batch_id=:batch_id ORDER BY i.order_index"
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .all()
            )
            inputs: list[TranslationInput] = []
            entries: list[tuple[str, str, str]] = []
            for row in rows:
                if str(row["status"]) != "running":
                    continue
                content_id = str(row["turn_id"] or row["report_revision_id"])
                content = self._resolve_source_text(
                    db,
                    debate_id=str(row["debate_id"]),
                    content_type=str(row["content_type"]),
                    content_id=content_id,
                    expected_hash=str(row["source_text_hash"]),
                )
                if content is None:
                    self._complete_item(
                        db,
                        batch_id=batch_id,
                        entry_id=str(row["entry_id"]),
                        status="failed",
                        safe_error_code=SOURCE_CHANGED,
                    )
                    continue
                inputs.append(
                    TranslationInput(
                        content_type=str(row["content_type"]),
                        content_id=content_id,
                        source_text=content,
                        source_text_hash=str(row["source_text_hash"]),
                    )
                )
                entries.append((str(row["entry_id"]), str(row["debate_id"]), content_id))

            outputs: Sequence[TranslationOutput]
            if inputs:
                started = self.get_batch(db, batch_id=batch_id)
                self._publish_event("translation.batch_started", started)
                try:
                    outputs = self.provider.translate_batch(inputs)
                except Exception:
                    outputs = tuple(TranslationOutput(None, PROVIDER_FAILED) for _ in inputs)
                if len(outputs) != len(inputs):
                    outputs = tuple(TranslationOutput(None, PROVIDER_FAILED) for _ in inputs)
                for (entry_id, _debate_id, _content_id), output in zip(
                    entries,
                    outputs,
                    strict=True,
                ):
                    if output.translated_text is not None:
                        self._complete_item(
                            db,
                            batch_id=batch_id,
                            entry_id=entry_id,
                            status="ready",
                            safe_error_code=None,
                            translated_text=output.translated_text,
                        )
                    else:
                        self._complete_item(
                            db,
                            batch_id=batch_id,
                            entry_id=entry_id,
                            status="failed",
                            safe_error_code=output.safe_error_code or PROVIDER_FAILED,
                        )

            _begin_immediate(db)
            # Only items owned and claimed by this batch may fail here. Reused
            # active entries remain pending until their generation owner
            # publishes a ready immutable cache row.
            db.execute(
                text(
                    "UPDATE translation_batch_items SET status='failed', "
                    "safe_error_code=:code WHERE batch_id=:batch_id "
                    "AND status='running'"
                ),
                {"batch_id": batch_id, "code": PROVIDER_FAILED},
            )
            db.execute(
                text(
                    "UPDATE translation_entries SET status='failed', safe_error_code=:code, "
                    "translated_text=NULL, updated_at=:updated_at WHERE id IN "
                    "(SELECT entry_id FROM translation_batch_items WHERE batch_id=:batch_id "
                    "AND status='failed') AND status IN ('pending','running')"
                ),
                {"batch_id": batch_id, "code": PROVIDER_FAILED, "updated_at": _now()},
            )
            counts = Counter(
                str(row[0])
                for row in db.execute(
                    text("SELECT status FROM translation_batch_items WHERE batch_id=:batch_id"),
                    {"batch_id": batch_id},
                ).all()
            )
            succeeded = counts["ready"]
            failed = counts["failed"]
            pending = counts["pending"] + counts["running"]
            status = (
                "pending"
                if pending > 0
                else "completed"
                if failed == 0
                else "partial"
                if succeeded > 0
                else "failed"
            )
            self._set_batch_counts(db, batch_id, status=status, now=_now())
            if status == "pending":
                self._release_job_pending(db, batch_id=batch_id)
            else:
                self._finish_job(
                    db,
                    batch_id=batch_id,
                    status="failed" if status == "failed" else "completed",
                )
            db.commit()
            result = self.get_batch(db, batch_id=batch_id)
        except Exception:
            db.rollback()
            self._mark_batch_failed(batch_id, PROVIDER_FAILED)
            result = self._safe_get_batch(batch_id)
        finally:
            db.close()

        if result is not None:
            event_type = {
                "completed": "translation.batch_completed",
                "partial": "translation.batch_completed",
                "failed": "translation.batch_failed",
            }.get(result.status)
            if event_type:
                self._publish_event(event_type, result)
        return result

    async def run_batch_async(self, batch_id: str) -> TranslationBatchDTO | None:
        return await asyncio.to_thread(self.run_batch, batch_id)

    def _resolve_source_text(
        self,
        db: Session,
        *,
        debate_id: str,
        content_type: str,
        content_id: str,
        expected_hash: str,
    ) -> str | None:
        if content_type == "turn":
            row = db.execute(
                text(
                    "SELECT speech FROM debate_turns WHERE id=:content_id AND debate_id=:debate_id "
                    "AND publication_status='public' AND generation_status='final_ready'"
                ),
                {"content_id": content_id, "debate_id": debate_id},
            ).first()
        elif content_type == "report_revision":
            try:
                row = db.execute(
                    text(
                        "SELECT english_markdown FROM civilization_report_revisions "
                        "WHERE id=:content_id AND debate_id=:debate_id AND status='ready'"
                    ),
                    {"content_id": content_id, "debate_id": debate_id},
                ).first()
            except OperationalError:
                row = None
        else:
            return None
        if row is None or not isinstance(row[0], str) or not row[0]:
            return None
        return row[0] if source_text_hash(row[0]) == expected_hash else None

    def _complete_item(
        self,
        db: Session,
        *,
        batch_id: str,
        entry_id: str,
        status: str,
        safe_error_code: str | None,
        translated_text: str | None = None,
    ) -> None:
        _begin_immediate(db)
        if status == "ready":
            changed = db.execute(
                text(
                    "UPDATE translation_entries SET status='ready', translated_text=:text, "
                    "safe_error_code=NULL, updated_at=:updated_at WHERE id=:entry_id "
                    "AND status='running'"
                ),
                {"entry_id": entry_id, "text": translated_text, "updated_at": _now()},
            )
        else:
            changed = db.execute(
                text(
                    "UPDATE translation_entries SET status='failed', translated_text=NULL, "
                    "safe_error_code=:code, updated_at=:updated_at WHERE id=:entry_id "
                    "AND status='running'"
                ),
                {
                    "entry_id": entry_id,
                    "code": safe_error_code or PROVIDER_FAILED,
                    "updated_at": _now(),
                },
            )
        if getattr(changed, "rowcount", 0) != 1:
            db.rollback()
            return
        db.execute(
            text(
                "UPDATE translation_batch_items SET status=:status, safe_error_code=:code "
                "WHERE batch_id=:batch_id AND entry_id=:entry_id "
                "AND status='running'"
            ),
            {
                "batch_id": batch_id,
                "entry_id": entry_id,
                "status": status,
                "code": safe_error_code if status == "failed" else None,
            },
        )
        db.commit()

    def _finish_job(self, db: Session, *, batch_id: str, status: str) -> None:
        columns = _table_columns(db, "jobs")
        if "translation_batch_id" not in columns:
            return
        db.execute(
            text(
                "UPDATE jobs SET state=:state, safe_error_code=:safe_error_code, "
                "updated_at=:updated_at WHERE translation_batch_id=:batch_id "
                "AND operation=:operation AND state IN ('pending','running')"
            ),
            {
                "state": status,
                "safe_error_code": PROVIDER_FAILED if status == "failed" else None,
                "updated_at": _now(),
                "batch_id": batch_id,
                "operation": TRANSLATION_JOB_OPERATION,
            },
        )

    def _release_job_pending(self, db: Session, *, batch_id: str) -> None:
        db.execute(
            text(
                "UPDATE jobs SET state='pending', safe_error_code=NULL, updated_at=:updated_at "
                "WHERE translation_batch_id=:batch_id AND operation=:operation "
                "AND state='running'"
            ),
            {
                "updated_at": _now(),
                "batch_id": batch_id,
                "operation": TRANSLATION_JOB_OPERATION,
            },
        )

    def _mark_batch_failed(self, batch_id: str, code: str) -> None:
        db = self._session()
        try:
            _begin_immediate(db)
            db.execute(
                text(
                    "UPDATE translation_batch_items SET status='failed', safe_error_code=:code "
                    "WHERE batch_id=:batch_id AND status IN ('pending','running')"
                ),
                {"batch_id": batch_id, "code": code},
            )
            db.execute(
                text(
                    "UPDATE translation_entries SET status='failed', translated_text=NULL, "
                    "safe_error_code=:code, updated_at=:updated_at WHERE id IN "
                    "(SELECT entry_id FROM translation_batch_items WHERE batch_id=:batch_id "
                    "AND status='failed' AND reused=0) AND status IN ('pending','running')"
                ),
                {"batch_id": batch_id, "code": code, "updated_at": _now()},
            )
            counts = Counter(
                str(row[0])
                for row in db.execute(
                    text("SELECT status FROM translation_batch_items WHERE batch_id=:batch_id"),
                    {"batch_id": batch_id},
                ).all()
            )
            total = sum(counts.values())
            status = (
                "completed"
                if total > 0 and counts["ready"] == total
                else "partial"
                if counts["ready"] > 0 and counts["failed"] > 0
                else "failed"
            )
            self._set_batch_counts(db, batch_id, status=status, now=_now())
            self._finish_job(db, batch_id=batch_id, status="failed")
            db.commit()
        finally:
            db.close()

    def _safe_get_batch(self, batch_id: str) -> TranslationBatchDTO | None:
        try:
            db = self._session()
        except RuntimeError:
            return None
        try:
            return self.get_batch(db, batch_id=batch_id)
        except (PlatformError, OperationalError):
            return None
        finally:
            db.close()

    def recover_startup(self, db: Session) -> tuple[str, ...]:
        """Fail running jobs/entries after restart and return pending IDs."""

        if not _has_table(db, "translation_batches") or not _has_table(db, "jobs"):
            return ()
        if "translation_batch_id" not in _table_columns(db, "jobs"):
            return ()
        _begin_immediate(db)
        running = [
            str(row[0])
            for row in db.execute(
                text(
                    "SELECT translation_batch_id FROM jobs WHERE operation=:operation "
                    "AND state='running' AND translation_batch_id IS NOT NULL"
                ),
                {"operation": TRANSLATION_JOB_OPERATION},
            ).all()
        ]
        for batch_id in running:
            db.execute(
                text(
                    "UPDATE translation_batch_items SET status='failed', "
                    "safe_error_code=:code WHERE batch_id=:batch_id "
                    "AND status IN ('pending','running')"
                ),
                {"batch_id": batch_id, "code": OPERATION_INTERRUPTED},
            )
            db.execute(
                text(
                    "UPDATE translation_entries SET status='failed', translated_text=NULL, "
                    "safe_error_code=:code, updated_at=:updated_at WHERE id IN "
                    "(SELECT entry_id FROM translation_batch_items WHERE batch_id=:batch_id "
                    "AND status='failed' AND reused=0) AND status IN ('pending','running')"
                ),
                {"batch_id": batch_id, "code": OPERATION_INTERRUPTED, "updated_at": _now()},
            )
            counts = Counter(
                str(row[0])
                for row in db.execute(
                    text("SELECT status FROM translation_batch_items WHERE batch_id=:batch_id"),
                    {"batch_id": batch_id},
                ).all()
            )
            total = sum(counts.values())
            status = (
                "completed"
                if total > 0 and counts["ready"] == total
                else "partial"
                if counts["ready"] > 0 and counts["failed"] > 0
                else "failed"
            )
            db.execute(
                text(
                    "UPDATE translation_batches SET status=:status, total_items=:total, "
                    "succeeded_items=:succeeded, failed_items=:failed, updated_at=:updated_at "
                    "WHERE id=:batch_id"
                ),
                {
                    "batch_id": batch_id,
                    "status": status,
                    "total": total,
                    "succeeded": counts["ready"],
                    "failed": counts["failed"],
                    "updated_at": _now(),
                },
            )
            db.execute(
                text(
                    "UPDATE jobs SET state='interrupted', safe_error_code=:code, "
                    "updated_at=:updated_at WHERE translation_batch_id=:batch_id "
                    "AND operation=:operation AND state='running'"
                ),
                {
                    "batch_id": batch_id,
                    "operation": TRANSLATION_JOB_OPERATION,
                    "code": OPERATION_INTERRUPTED,
                    "updated_at": _now(),
                },
            )
        pending_rows = db.execute(
            text(
                "SELECT translation_batch_id, COUNT(*) AS owner_count FROM jobs "
                "WHERE translation_batch_id IS NOT NULL GROUP BY translation_batch_id "
                "HAVING owner_count=1 AND MIN(operation)=:operation "
                "AND MIN(state)='pending' "
            ),
            {"operation": TRANSLATION_JOB_OPERATION},
        ).all()
        pending = tuple(sorted(str(row[0]) for row in pending_rows))
        db.commit()
        return pending

    def schedule_pending(self, db: Session) -> tuple[str, ...]:
        ids = self.recover_startup(db)
        # ``recover_startup`` returns pending IDs and marks running failures;
        # a parent lifespan can call this helper and enqueue each ID once.
        return ids

    async def startup_recover_and_schedule(self) -> tuple[str, ...]:
        """Lifespan hook: recover once, then enqueue each valid pending owner."""

        db = self._session()
        try:
            pending = self.recover_startup(db)
        finally:
            db.close()
        for batch_id in pending:
            await self.task_manager.enqueue(self, batch_id)
        return pending


def _context_for_user(db: Session, actor_user_id: str) -> AuthContext:
    """Build a minimal internal context for the shared idempotency helper."""

    from app.core.models import SessionRecord, User

    user = db.get(User, actor_user_id)
    if user is None:
        raise not_found()
    # The route already authenticated this actor.  The generic helper only
    # needs the stable actor ID and a non-empty token for its own key scope;
    # no token is persisted in the idempotency record.
    session = SessionRecord(
        id_hash="translation-internal-session",
        user_id=actor_user_id,
        csrf_hash="translation-internal-csrf",
        expires_at=_now() + timedelta(minutes=1),
        created_at=_now(),
        revoked_at=None,
    )
    # ``claim_idempotency`` only uses ``context.user.id``.  This synthetic
    # context deliberately carries no usable session/CSRF credential.
    return AuthContext("", session, user, "")


def _abandon_claim_safely(db: Session, record: IdempotencyRecord) -> None:
    try:
        abandon_idempotency(db, record)
    except Exception:
        db.rollback()


def translated_text_for(
    db: Session,
    *,
    debate_id: str,
    content_type: str,
    content_id: str,
    source_text: str,
    target_language: str = TARGET_LANGUAGE,
    policy_key: str = MOCK_POLICY_KEY,
    quality_key: str = MOCK_QUALITY_KEY,
) -> str | None:
    """Read only an exact ready cache entry for one immutable source."""

    if not _has_table(db, "translation_entries"):
        return None
    quality = _quality_column(db, "translation_entries")
    identity_column = "turn_id" if content_type == "turn" else "report_revision_id"
    other_column = "report_revision_id" if content_type == "turn" else "turn_id"
    row = db.execute(
        text(
            "SELECT translated_text FROM translation_entries WHERE debate_id=:debate_id "
            "AND content_type=:content_type AND "
            f"{identity_column}=:content_id AND {other_column} IS NULL "
            "AND source_text_hash=:source_text_hash AND target_language=:target_language "
            f"AND policy_key=:policy_key AND {quality}=:quality_value AND status='ready' "
            "ORDER BY created_at, id LIMIT 1"
        ),
        {
            "debate_id": debate_id,
            "content_type": content_type,
            "content_id": content_id,
            "source_text_hash": source_text_hash(source_text),
            "target_language": target_language,
            "policy_key": policy_key,
            "quality_value": quality_key,
        },
    ).first()
    return str(row[0]) if row is not None and isinstance(row[0], str) else None


def attach_translated_text(
    db: Session,
    *,
    debate_id: str,
    turns: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Add exact ready derived fields to history read models only.

    The returned copies are intentionally detached from the input mappings;
    this makes it impossible for a caller to mutate the authoritative
    transcript object and accidentally send derived text into generation.
    """

    projected: list[dict[str, Any]] = []
    for turn in turns:
        row = dict(turn)
        turn_id = row.get("id") or row.get("turn_id")
        speech = row.get("speech") or row.get("original_text")
        row["translated_text"] = (
            translated_text_for(
                db,
                debate_id=debate_id,
                content_type="turn",
                content_id=str(turn_id),
                source_text=str(speech),
            )
            if turn_id is not None and isinstance(speech, str) and speech
            else None
        )
        projected.append(row)
    return tuple(projected)


def attach_translated_report(
    db: Session,
    *,
    debate_id: str,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Add one exact ready derived field to a report history read model."""

    row = dict(report)
    revision_id = row.get("id") or row.get("revision_id")
    markdown = row.get("english_markdown") or row.get("original_text")
    row["translated_markdown"] = (
        translated_text_for(
            db,
            debate_id=debate_id,
            content_type="report_revision",
            content_id=str(revision_id),
            source_text=str(markdown),
        )
        if revision_id is not None and isinstance(markdown, str) and markdown
        else None
    )
    return row


# Backwards-friendly names for the main integration worker/read-model wiring.
apply_translations_to_transcript = attach_translated_text
get_translated_text = translated_text_for


async def startup_translation_service(service: TranslationService) -> tuple[str, ...]:
    """Public lifespan hook for main integration without importing internals."""

    return await service.startup_recover_and_schedule()


__all__ = [
    "OPERATION_INTERRUPTED",
    "PROVIDER_FAILED",
    "SOURCE_CHANGED",
    "TARGET_LANGUAGE",
    "TRANSLATION_JOB_OPERATION",
    "TRANSLATION_OPERATION",
    "TranslationEventPayload",
    "TranslationService",
    "TranslationTaskManager",
    "apply_translations_to_transcript",
    "attach_translated_text",
    "attach_translated_report",
    "get_translated_text",
    "startup_translation_service",
    "translated_text_for",
]
