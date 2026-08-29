"""Canonical TranslationInputManifestV1 construction and hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import not_found

TARGET_LANGUAGE = "zh-Hans"
MANIFEST_VERSION = "TranslationInputManifestV1"
MOCK_POLICY_KEY = "mock_translation_v1"
MOCK_QUALITY_KEY = "test_representation"


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize canonical JSON as UTF-8 without BOM or lossy normalization."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def source_text_hash(source_text: str) -> str:
    """Hash authoritative English bytes exactly as stored."""

    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def manifest_hash(manifest: TranslationInputManifestV1 | Mapping[str, Any]) -> str:
    value = (
        manifest.canonical_dict() if isinstance(manifest, TranslationInputManifestV1) else manifest
    )
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class ManifestTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    turn_index: int = Field(ge=0)
    source_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManifestReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_revision_id: UUID
    source_text_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class TranslationInputManifestV1(BaseModel):
    """Closed, content-only input identity for one translation batch.

    The manifest deliberately contains IDs and hashes, never source text.  A
    worker resolves the exact source bytes again from immutable rows and
    checks the hash before calling its provider.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(default=MANIFEST_VERSION, pattern=r"^TranslationInputManifestV1$")
    debate_id: UUID
    turns: list[ManifestTurn]
    report: ManifestReport | None = None
    target_language: str = Field(default=TARGET_LANGUAGE, pattern=r"^zh-Hans$")
    policy_key: str = Field(default=MOCK_POLICY_KEY, min_length=1)
    quality_key: str = Field(default=MOCK_QUALITY_KEY, min_length=1)

    def canonical_dict(self) -> dict[str, Any]:
        """Return the exact sorted-by-contract representation."""

        # Pydantic preserves array order; turns were sorted by turn_index and
        # report is a single trailing optional content identity by contract.
        value = self.model_dump(mode="json", exclude_none=False)
        value["turns"] = [
            item.model_dump(mode="json")
            for item in sorted(self.turns, key=lambda row: (row.turn_index, str(row.turn_id)))
        ]
        return value

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_dict())

    @property
    def input_hash(self) -> str:
        return manifest_hash(self)

    @property
    def item_count(self) -> int:
        return len(self.turns) + (1 if self.report is not None else 0)


@dataclass(frozen=True, slots=True)
class ManifestSource:
    content_type: str
    content_id: str
    order_index: int
    source_text: str
    source_text_hash: str


def _safe_rows(
    session: Session,
    statement: str,
    parameters: Mapping[str, Any],
) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in session.execute(text(statement), parameters).mappings().all()]
    except OperationalError:
        # Isolated Wave 0-2 databases intentionally have no report tables. A
        # missing optional report source is equivalent to no current report.
        return []


def _current_ready_report(session: Session, debate_id: str) -> tuple[str, str] | None:
    """Resolve only M14's exact current-success pointer, never latest-ready."""

    rows = _safe_rows(
        session,
        "SELECT p.revision_id, r.english_markdown "
        "FROM civilization_report_current_success p "
        "JOIN civilization_report_revisions r "
        "  ON r.id=p.revision_id AND r.report_id=p.report_id AND r.debate_id=p.debate_id "
        "WHERE p.debate_id=:debate_id AND p.revision_status='ready' AND r.status='ready' "
        "ORDER BY r.revision_no DESC LIMIT 1",
        {"debate_id": debate_id},
    )
    if not rows:
        return None
    row = rows[0]
    text_value = row.get("english_markdown")
    revision_id = row.get("revision_id")
    if not isinstance(revision_id, str) or not isinstance(text_value, str) or not text_value:
        return None
    return revision_id, text_value


def collect_manifest_sources(
    session: Session,
    debate_id: str,
    *,
    target_language: str = TARGET_LANGUAGE,
    policy_key: str = MOCK_POLICY_KEY,
    quality_key: str = MOCK_QUALITY_KEY,
) -> tuple[TranslationInputManifestV1, tuple[ManifestSource, ...]]:
    """Read the immutable public/final-ready source set in canonical order."""

    debate = session.execute(
        text("SELECT id FROM debates WHERE id=:debate_id"), {"debate_id": debate_id}
    ).first()
    if debate is None:
        raise not_found()
    rows = (
        session.execute(
            text(
                "SELECT id, turn_index, speech FROM debate_turns "
                "WHERE debate_id=:debate_id AND publication_status='public' "
                "AND generation_status='final_ready' AND speech IS NOT NULL "
                "ORDER BY turn_index, id"
            ),
            {"debate_id": debate_id},
        )
        .mappings()
        .all()
    )
    sources: list[ManifestSource] = []
    turns: list[ManifestTurn] = []
    for row in rows:
        turn_id = str(row["id"])
        source = row["speech"]
        if not isinstance(source, str) or not source:
            continue
        turn_index = int(row["turn_index"])
        digest = source_text_hash(source)
        turns.append(
            ManifestTurn(
                turn_id=UUID(turn_id),
                turn_index=turn_index,
                source_text_hash=digest,
            )
        )
        sources.append(ManifestSource("turn", turn_id, turn_index, source, digest))

    report_source = _current_ready_report(session, debate_id)
    report: ManifestReport | None = None
    if report_source is not None:
        revision_id, report_text = report_source
        report = ManifestReport(
            report_revision_id=UUID(revision_id),
            source_text_hash=source_text_hash(report_text),
        )
        sources.append(
            ManifestSource(
                "report_revision",
                revision_id,
                len(sources),
                report_text,
                source_text_hash(report_text),
            )
        )
    manifest = TranslationInputManifestV1(
        debate_id=UUID(debate_id),
        turns=turns,
        report=report,
        target_language=target_language,
        policy_key=policy_key,
        quality_key=quality_key,
    )
    sources.sort(
        key=lambda item: (
            0 if item.content_type == "turn" else 1,
            item.order_index,
            item.content_id,
        )
    )
    return manifest, tuple(sources)


def build_translation_manifest(
    session: Session,
    debate_id: str,
    *,
    target_language: str = TARGET_LANGUAGE,
    policy_key: str = MOCK_POLICY_KEY,
    quality_key: str = MOCK_QUALITY_KEY,
) -> TranslationInputManifestV1:
    """Public helper used by routes and tests."""

    manifest, _ = collect_manifest_sources(
        session,
        debate_id,
        target_language=target_language,
        policy_key=policy_key,
        quality_key=quality_key,
    )
    return manifest


__all__ = [
    "MANIFEST_VERSION",
    "MOCK_POLICY_KEY",
    "MOCK_QUALITY_KEY",
    "TARGET_LANGUAGE",
    "ManifestReport",
    "ManifestSource",
    "ManifestTurn",
    "TranslationInputManifestV1",
    "build_translation_manifest",
    "canonical_json_bytes",
    "collect_manifest_sources",
    "manifest_hash",
    "source_text_hash",
]
