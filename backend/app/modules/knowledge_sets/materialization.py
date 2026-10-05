"""Per-item, restart-safe materialization of an accepted Knowledge stage."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError
from app.core.models import Job, ProviderOperation
from app.modules.knowledge_sets.generation import (
    GENERATION_OPERATION,
    _current_generation_authorized,
    _finish_blocked,
    _start_immediate,
)
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeGenerationAcceptedStage,
    KnowledgeGenerationItem,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeGenerationTargetSnapshot,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import (
    AssetCitation,
    AssetContent,
    ConceptContent,
    NoteContent,
    QuestionContent,
)
from app.modules.knowledge_sets.service import (
    now_utc,
    save_generated_knowledge_asset,
    save_knowledge_markdown_version,
)

_ASSET_CONTENT: TypeAdapter[AssetContent] = TypeAdapter(AssetContent)


def _heading(value: str) -> str:
    return " ".join(value.split()) or "Knowledge"


def _quoted(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return "\n".join("> " + line for line in escaped.splitlines())


def _render_asset_versions(
    db: Session,
    set_row: KnowledgeSet,
    items: Sequence[KnowledgeGenerationItem],
) -> tuple[str, str, list[str]]:
    concepts: list[tuple[str, ConceptContent]] = []
    questions: list[tuple[str, QuestionContent]] = []
    notes: list[tuple[str, NoteContent]] = []
    version_ids: list[str] = []
    for item in items:
        if item.asset_version_id is None or item.asset_id is None:
            raise ValueError("applied generation item has no Asset version")
        version = db.get(KnowledgeAssetVersion, item.asset_version_id)
        if version is None or version.asset_id != item.asset_id:
            raise ValueError("generation item Asset version is unavailable")
        content = _ASSET_CONTENT.validate_python(json.loads(version.content_json))
        if content.kind == "concept":
            concepts.append((item.asset_id, content))
        elif content.kind == "question":
            questions.append((item.asset_id, content))
        else:
            notes.append((item.asset_id, content))
        version_ids.append(version.id)

    full_sections = [f"# {_heading(set_row.display_name)}"]
    student_sections = [f"# {_heading(set_row.display_name)}"]
    if concepts:
        full_sections.append(
            "## Concepts\n\n"
            + "\n\n".join(
                f"### {_heading(content.title)}\n\n{content.description}".rstrip()
                for _asset_id, content in concepts
            )
        )
        student_sections.append(
            "## Concepts\n\n"
            + "\n\n".join(
                f"### {_heading(content.title)}\n\n{_quoted(content.description)}".rstrip()
                for _asset_id, content in concepts
            )
        )
        titles = {asset_id: content.title for asset_id, content in concepts}
        graph_edges = [
            f"- {_heading(content.title)} → {_heading(titles[target])}"
            for _asset_id, content in concepts
            for target in map(str, content.prerequisite_ids)
            if target in titles
        ]
        if graph_edges:
            full_sections.append("## Graph\n\n" + "\n".join(graph_edges))
            student_sections.append("## Graph\n\n" + "\n".join(graph_edges))
    if questions:
        full_question_blocks: list[str] = []
        student_question_blocks: list[str] = []
        for index, (_asset_id, content) in enumerate(questions, start=1):
            block = f"### Question {index}\n\n{content.prompt}"
            if content.rubric.criteria:
                block += "\n\n#### Rubric\n\n" + "\n".join(
                    f"- **{criterion.label}** ({criterion.points:g}): {criterion.guidance}"
                    for criterion in content.rubric.criteria
                )
                if content.rubric.total_points is not None:
                    block += f"\n\nTotal: {content.rubric.total_points:g} points"
            if content.reference_answer is not None:
                block += f"\n\n#### Reference answer\n\n{content.reference_answer}"
            full_question_blocks.append(block)
            student_question_blocks.append(f"### Question {index}\n\n{_quoted(content.prompt)}")
        full_sections.append("## Questions\n\n" + "\n\n".join(full_question_blocks))
        student_sections.append("## Questions\n\n" + "\n\n".join(student_question_blocks))
    if notes:
        full_sections.append(
            "## Notes\n\n"
            + "\n\n".join(
                f"### {_heading(content.title)}\n\n{content.body}".rstrip()
                for _asset_id, content in notes
            )
        )
        student_sections.append(
            "## Notes\n\n"
            + "\n\n".join(
                f"### {_heading(content.title)}\n\n{_quoted(content.body)}".rstrip()
                for _asset_id, content in notes
            )
        )
    return (
        "\n\n".join(full_sections),
        "\n\n".join(student_sections),
        version_ids,
    )


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _raw_stage_assets(stage: KnowledgeGenerationAcceptedStage) -> list[object]:
    if stage.canonical_stage_json is None:
        raise ValueError("accepted stage content was suppressed")
    if _sha256(stage.canonical_stage_json) != stage.canonical_stage_hash:
        raise ValueError("accepted stage digest does not match")
    try:
        payload = json.loads(stage.canonical_stage_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("accepted stage is not JSON") from exc
    if not isinstance(payload, dict) or _canonical(payload) != stage.canonical_stage_json:
        raise ValueError("accepted stage is not canonical")
    assets = payload.get("assets")
    if not isinstance(assets, list) or len(assets) != stage.item_count:
        raise ValueError("accepted stage item count does not match")
    return assets


def _candidate_parts(raw: object) -> tuple[dict[str, Any] | None, list[str], bool]:
    if not isinstance(raw, dict):
        return None, [], False
    if raw.get("_item_error") == "provider_asset_invalid":
        return None, [], False
    if "content" in raw:
        if set(raw) != {"content", "source_receipt_ids", "citation_unverified"}:
            return None, [], False
        content = raw.get("content")
        receipts = raw.get("source_receipt_ids")
        citation_unverified = raw.get("citation_unverified")
        if (
            not isinstance(content, dict)
            or not isinstance(receipts, list)
            or any(not isinstance(receipt, str) for receipt in receipts)
            or not isinstance(citation_unverified, bool)
        ):
            return None, [], False
        return content, cast(list[str], receipts), citation_unverified
    # Accepted K2b1 v1 stages contain the typed asset fields directly and have
    # no receipt list. Keep them materializable after a rolling upgrade.
    return raw, [], False


def _item_key(run_id: str, stage_hash: str, item_index: int) -> str:
    return _sha256(
        _canonical({"run_id": run_id, "stage_hash": stage_hash, "item_index": item_index})
    )


def _lineage_key(run: KnowledgeGenerationRun, kind: str, ordinal: int) -> str:
    return _sha256(
        _canonical(
            {
                "agent_id": run.agent_id,
                "set_id": run.knowledge_set_id,
                "kind": kind,
                "ordinal": ordinal,
            }
        )
    )


def _target_heads(asset_heads_json: str) -> dict[str, tuple[str, int, str]] | None:
    try:
        raw = json.loads(asset_heads_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, list) or _canonical(raw) != asset_heads_json:
        return None
    result: dict[str, tuple[str, int, str]] = {}
    for value in raw:
        if (
            not isinstance(value, dict)
            or set(value) != {"lineage_key", "asset_id", "version_seq", "origin"}
            or not isinstance(value.get("lineage_key"), str)
            or len(value["lineage_key"]) != 64
            or not isinstance(value.get("asset_id"), str)
            or not isinstance(value.get("version_seq"), int)
            or isinstance(value.get("version_seq"), bool)
            or value["version_seq"] < 1
            or value.get("origin") not in {"ai", "manual"}
            or value["lineage_key"] in result
        ):
            return None
        result[value["lineage_key"]] = (
            value["asset_id"],
            value["version_seq"],
            value["origin"],
        )
    return result


def _receipt_citations(
    db: Session,
    run: KnowledgeGenerationRun,
    set_row: KnowledgeSet,
    receipt_ids: Sequence[str],
    *,
    initially_unverified: bool,
) -> tuple[list[AssetCitation], int]:
    citations: list[AssetCitation] = []
    unverified_count = int(initially_unverified)
    seen: set[str] = set()
    for receipt_id in receipt_ids:
        if receipt_id in seen:
            unverified_count += 1
            continue
        seen.add(receipt_id)
        receipt = db.get(KnowledgeGenerationSourceReceipt, receipt_id)
        if receipt is None or receipt.run_id != run.id:
            unverified_count += 1
            continue
        binding = db.get(KnowledgeSetSource, receipt.source_binding_id)
        if (
            binding is None
            or binding.knowledge_set_id != set_row.id
            or not binding.is_active
            or binding.document_id != receipt.document_id
            or binding.stored_file_id != receipt.stored_file_id
            or binding.source_content_hash != receipt.source_content_hash
            or binding.source_file_sha256 != receipt.source_file_sha256
            or binding.source_authorization_epoch != receipt.source_authorization_epoch
            or binding.source_index_revision != receipt.source_index_revision
        ):
            unverified_count += 1
            continue
        try:
            citations.append(AssetCitation(source_binding_id=UUID(binding.id)))
        except (TypeError, ValueError):
            unverified_count += 1
    return citations, unverified_count


def _current_owner_stage(
    db: Session, run_id: str, claim_token: str
) -> (
    tuple[
        KnowledgeGenerationRun,
        KnowledgeGenerationAcceptedStage,
        ProviderOperation,
        Job,
    ]
    | None
):
    run = db.scalar(
        select(KnowledgeGenerationRun)
        .where(
            KnowledgeGenerationRun.id == run_id,
            KnowledgeGenerationRun.state == "running",
            KnowledgeGenerationRun.claim_token == claim_token,
        )
        .with_for_update()
    )
    if run is None or run.provider_operation_id is None:
        return None
    stage = db.get(KnowledgeGenerationAcceptedStage, run.id)
    operation = db.get(ProviderOperation, run.provider_operation_id)
    job = db.get(Job, run.job_id)
    if (
        stage is None
        or operation is None
        or job is None
        or job.operation != GENERATION_OPERATION
        or job.claim_token != claim_token
        or operation.provider_operation != "llm_knowledge_generate"
        or operation.state != "accepted"
        or operation.id != stage.operation_id
        or run.request_hash != stage.request_hash
        or operation.request_hash != stage.request_hash
        or run.provider_manifest_hash != stage.manifest_hash
        or operation.export_manifest_hash != stage.manifest_hash
        or operation.staged_response_hash != stage.canonical_stage_hash
    ):
        return None
    return run, stage, operation, job


def _record_failed_item(
    session_factory: Callable[[], Session],
    *,
    run_id: str,
    claim_token: str,
    stage_hash: str,
    item_index: int,
    item_key: str,
    candidate_hash: str,
    kind: str,
    safe_error_code: str,
) -> None:
    with session_factory() as db:
        db.rollback()
        _start_immediate(db)
        owner_stage = _current_owner_stage(db, run_id, claim_token)
        if owner_stage is None:
            db.rollback()
            return
        run, _stage, _operation, _job = owner_stage
        if not _current_generation_authorized(db, run):
            _finish_blocked(db, run, _job, "authorization_revoked")
            db.commit()
            return
        item = db.scalar(
            select(KnowledgeGenerationItem).where(
                KnowledgeGenerationItem.run_id == run.id,
                KnowledgeGenerationItem.item_key == item_key,
            )
        )
        if item is not None and item.state in {"applied", "failed", "skipped"}:
            db.rollback()
            return
        if item is None:
            timestamp = now_utc()
            item = KnowledgeGenerationItem(
                id=str(uuid4()),
                run_id=run.id,
                stage_hash=stage_hash,
                item_key=item_key,
                item_index=item_index,
                kind=kind,
                lineage_key=None,
                candidate_hash=candidate_hash,
                source_receipt_ids_json="[]",
                citation_unverified_count=0,
                state="failed",
                safe_error_code=safe_error_code,
                asset_id=None,
                asset_version_id=None,
                expected_asset_version_seq=None,
                created_at=timestamp,
                updated_at=timestamp,
            )
            db.add(item)
        else:
            item.state = "failed"
            item.safe_error_code = safe_error_code
            item.asset_version_id = None
            item.updated_at = now_utc()
        db.commit()


def _materialize_one(
    session_factory: Callable[[], Session],
    *,
    run_id: str,
    claim_token: str,
    stage_hash: str,
    item_index: int,
    raw_candidate: object,
    lineage_ordinal: int,
    data_root: Path,
) -> str:
    item_key = _item_key(run_id, stage_hash, item_index)
    candidate_hash = _sha256(_canonical(raw_candidate))
    candidate, receipt_ids, citation_warning = _candidate_parts(raw_candidate)
    kind = str(candidate.get("kind")) if candidate is not None else "invalid"
    if kind not in {"concept", "question", "note"}:
        candidate = None
        kind = "invalid"
    lineage_key: str | None = None
    if candidate is not None:
        # The run row is read again under the item transaction below before
        # this key is used to locate an existing generated Asset.
        with session_factory() as db:
            run = db.get(KnowledgeGenerationRun, run_id)
            if run is None:
                return "stale"
            lineage_key = _lineage_key(run, kind, lineage_ordinal)
    receipts_json = _canonical(receipt_ids)

    try:
        with session_factory() as db:
            db.rollback()
            _start_immediate(db)
            owner_stage = _current_owner_stage(db, run_id, claim_token)
            if owner_stage is None:
                db.rollback()
                return "stale"
            run, stage, _operation, job = owner_stage
            target_snapshot = db.get(KnowledgeGenerationTargetSnapshot, run.id)
            target_heads = (
                _target_heads(target_snapshot.asset_heads_json)
                if target_snapshot is not None
                else None
            )
            if target_heads is None:
                _finish_blocked(db, run, job, "knowledge_target_snapshot_invalid")
                db.commit()
                return "blocked"
            if stage.canonical_stage_hash != stage_hash:
                _finish_blocked(db, run, job, "knowledge_stage_invalid")
                db.commit()
                return "blocked"
            if not _current_generation_authorized(db, run):
                _finish_blocked(db, run, job, "authorization_revoked")
                db.commit()
                return "blocked"

            item = db.scalar(
                select(KnowledgeGenerationItem).where(
                    KnowledgeGenerationItem.run_id == run.id,
                    KnowledgeGenerationItem.item_key == item_key,
                )
            )
            if item is not None:
                if item.stage_hash != stage_hash or item.candidate_hash != candidate_hash:
                    _finish_blocked(db, run, job, "knowledge_item_identity_conflict")
                    db.commit()
                    return "blocked"
                if item.state in {"applied", "failed", "skipped"}:
                    state = item.state
                    db.rollback()
                    return state
            else:
                timestamp = now_utc()
                item = KnowledgeGenerationItem(
                    id=str(uuid4()),
                    run_id=run.id,
                    stage_hash=stage_hash,
                    item_key=item_key,
                    item_index=item_index,
                    kind=kind,
                    lineage_key=lineage_key,
                    candidate_hash=candidate_hash,
                    source_receipt_ids_json=receipts_json,
                    citation_unverified_count=0,
                    state="pending",
                    safe_error_code=None,
                    asset_id=None,
                    asset_version_id=None,
                    expected_asset_version_seq=None,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                db.add(item)
                db.flush()

            if candidate is None:
                item.state = "failed"
                item.safe_error_code = "provider_asset_invalid"
                item.updated_at = now_utc()
                db.commit()
                return "failed"

            set_row = db.get(KnowledgeSet, run.knowledge_set_id)
            if set_row is None:
                _finish_blocked(db, run, job, "authorization_revoked")
                db.commit()
                return "blocked"
            try:
                content = _ASSET_CONTENT.validate_python(candidate)
            except ValidationError:
                item.state = "failed"
                item.safe_error_code = "provider_asset_invalid"
                item.updated_at = now_utc()
                db.commit()
                return "failed"

            citations, unverified_count = _receipt_citations(
                db,
                run,
                set_row,
                receipt_ids,
                initially_unverified=citation_warning,
            )
            content = content.model_copy(update={"citations": citations})

            asset = db.scalar(
                select(KnowledgeAsset)
                .where(
                    KnowledgeAsset.knowledge_set_id == set_row.id,
                    KnowledgeAsset.generation_lineage_key == lineage_key,
                )
                .with_for_update()
            )
            expected_seq: int | None = None
            if asset is not None:
                target_head = target_heads.get(cast(str, lineage_key))
                current_version = db.scalar(
                    select(KnowledgeAssetVersion).where(
                        KnowledgeAssetVersion.asset_id == asset.id,
                        KnowledgeAssetVersion.version_seq == asset.current_version_seq,
                    )
                )
                if target_head is None or target_head[0] != asset.id or current_version is None:
                    item.state = "skipped"
                    item.safe_error_code = "target_head_changed"
                    item.asset_id = asset.id
                    item.expected_asset_version_seq = asset.current_version_seq
                    item.citation_unverified_count = unverified_count
                    item.updated_at = now_utc()
                    db.commit()
                    return "skipped"
                # Content edits do not cancel an authorized generation intent.
                # The next generated version follows whatever version is
                # current when this item reaches its serialized save.
                expected_seq = asset.current_version_seq
            elif cast(str, lineage_key) in target_heads:
                item.state = "skipped"
                item.safe_error_code = "target_head_missing"
                item.expected_asset_version_seq = target_heads[cast(str, lineage_key)][1]
                item.citation_unverified_count = unverified_count
                item.updated_at = now_utc()
                db.commit()
                return "skipped"
            try:
                asset, version = save_generated_knowledge_asset(
                    db,
                    actor_user_id=run.owner_user_id,
                    set_id=set_row.id,
                    generation_lineage_key=cast(str, lineage_key),
                    expected_asset_version_seq=expected_seq,
                    content=content,
                    generator_agent_version_id=run.agent_version_id,
                    generation_job_id=run.job_id,
                    data_root=data_root,
                )
            except PlatformError as exc:
                if exc.code in {"knowledge_source_not_bound", "knowledge_source_access_changed"}:
                    _finish_blocked(db, run, job, "authorization_revoked")
                    db.commit()
                    return "blocked"
                item.state = "failed"
                item.safe_error_code = "provider_asset_invalid"
                item.citation_unverified_count = unverified_count
                item.updated_at = now_utc()
                db.commit()
                return "failed"
            item.state = "applied"
            item.safe_error_code = "citation_unverified" if unverified_count else None
            item.asset_id = asset.id
            item.asset_version_id = version.id
            item.expected_asset_version_seq = expected_seq
            item.citation_unverified_count = unverified_count
            item.updated_at = now_utc()
            db.commit()
            return "applied"
    except Exception:
        _record_failed_item(
            session_factory,
            run_id=run_id,
            claim_token=claim_token,
            stage_hash=stage_hash,
            item_index=item_index,
            item_key=item_key,
            candidate_hash=candidate_hash,
            kind=kind,
            safe_error_code="knowledge_asset_save_failed",
        )
        return "failed"


def _finish_materialization(
    session_factory: Callable[[], Session], run_id: str, claim_token: str
) -> None:
    with session_factory() as db:
        db.rollback()
        _start_immediate(db)
        owner_stage = _current_owner_stage(db, run_id, claim_token)
        if owner_stage is None:
            db.rollback()
            return
        run, stage, _operation, job = owner_stage
        if not _current_generation_authorized(db, run):
            _finish_blocked(db, run, job, "authorization_revoked")
            db.commit()
            return
        target_snapshot = db.get(KnowledgeGenerationTargetSnapshot, run.id)
        if target_snapshot is None or _target_heads(target_snapshot.asset_heads_json) is None:
            _finish_blocked(db, run, job, "knowledge_target_snapshot_invalid")
            db.commit()
            return
        items = db.scalars(
            select(KnowledgeGenerationItem)
            .where(
                KnowledgeGenerationItem.run_id == run.id,
                KnowledgeGenerationItem.stage_hash == stage.canonical_stage_hash,
            )
            .order_by(KnowledgeGenerationItem.item_index)
        ).all()
        item_states = [item.state for item in items]
        if len(item_states) != stage.item_count or any(state == "pending" for state in item_states):
            _finish_blocked(db, run, job, "knowledge_materialization_incomplete")
            db.commit()
            return
        applied_count = sum(1 for state in item_states if state == "applied")
        failed_count = sum(1 for state in item_states if state in {"failed", "skipped"})
        if stage.item_count == 0:
            failed_count = 1
        set_row = db.get(KnowledgeSet, run.knowledge_set_id)
        if set_row is None:
            _finish_blocked(db, run, job, "authorization_revoked")
            db.commit()
            return
        # A complete document is promoted as one version. Per-item Assets are
        # already durable historical projections, but a failed/partial refresh
        # cannot replace an existing complete Markdown head with half a result.
        promote_document = failed_count == 0 or (
            set_row.current_markdown_version_seq == 0 and applied_count > 0
        )
        if promote_document:
            applied_items = [item for item in items if item.state == "applied"]
            try:
                markdown, student_projection, asset_version_ids = _render_asset_versions(
                    db, set_row, applied_items
                )
            except (TypeError, ValueError, ValidationError):
                applied_items = []
                failed_count = max(failed_count, 1)
            else:
                try:
                    save_knowledge_markdown_version(
                        db,
                        set_id=set_row.id,
                        expected_version_seq=set_row.current_markdown_version_seq,
                        markdown=markdown,
                        actor_user_id=run.owner_user_id,
                        origin="ai",
                        generation_run_id=run.id,
                        generation_intent_seq=run.intent_generation,
                        source_manifest_hash=run.source_manifest_hash,
                        generator_agent_version_id=run.agent_version_id,
                        asset_version_ids=asset_version_ids,
                        student_projection_markdown=student_projection,
                    )
                except PlatformError as exc:
                    if exc.code in {"stale_revision", "authorization_revoked"}:
                        _finish_blocked(db, run, job, "authorization_revoked")
                        db.commit()
                        return
                    raise
        now = now_utc()
        if failed_count:
            run.state = "failed"
            run.safe_error_code = (
                "knowledge_generation_partial_failure"
                if applied_count
                else "knowledge_generation_no_assets"
                if stage.item_count == 0
                else "knowledge_generation_items_failed"
            )
            job.state = "failed"
            job.safe_error_code = run.safe_error_code
        else:
            run.state = "completed"
            run.safe_error_code = None
            job.state = "completed"
            job.safe_error_code = None
        run.claim_token = None
        run.lease_expires_at = None
        run.updated_at = now
        job.claim_token = None
        job.updated_at = now
        db.commit()


def materialize_accepted_knowledge_generation(
    session_factory: Callable[[], Session],
    run_id: str,
    claim_token: str,
    *,
    data_root: Path,
) -> None:
    """Apply each validated stage item in its own permission-fenced transaction."""

    with session_factory() as db:
        db.rollback()
        _start_immediate(db)
        owner_stage = _current_owner_stage(db, run_id, claim_token)
        if owner_stage is None:
            db.rollback()
            return
        run, stage, _operation, job = owner_stage
        if not _current_generation_authorized(db, run):
            _finish_blocked(db, run, job, "authorization_revoked")
            db.commit()
            return
        try:
            candidates = _raw_stage_assets(stage)
        except ValueError:
            _finish_blocked(db, run, job, "knowledge_stage_invalid")
            db.commit()
            return
        stage_hash = stage.canonical_stage_hash
        db.rollback()

    ordinals = {"concept": 0, "question": 0, "note": 0}
    for item_index, raw_candidate in enumerate(candidates):
        content, _receipts, _warning = _candidate_parts(raw_candidate)
        kind = content.get("kind") if content is not None else None
        ordinal = ordinals.get(kind, 0) if isinstance(kind, str) else 0
        if isinstance(kind, str) and kind in ordinals:
            ordinals[kind] += 1
        result = _materialize_one(
            session_factory,
            run_id=run_id,
            claim_token=claim_token,
            stage_hash=stage_hash,
            item_index=item_index,
            raw_candidate=raw_candidate,
            lineage_ordinal=ordinal,
            data_root=data_root,
        )
        if result in {"blocked", "stale"}:
            return
    _finish_materialization(session_factory, run_id, claim_token)


__all__ = ["materialize_accepted_knowledge_generation"]
