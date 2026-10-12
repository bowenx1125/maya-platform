"""Add canonical, versioned Brainform Markdown to generated Knowledge Sets."""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0047_brainform_markdown"
down_revision: str | Sequence[str] | None = "0046_chat_withdrawal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _markdown_for_legacy_assets(rows: list[tuple[str, str, str]], name: str) -> tuple[str, str]:
    grouped: dict[str, list[str]] = {"concept": [], "question": [], "note": []}
    student_grouped: dict[str, list[str]] = {"concept": [], "question": [], "note": []}
    version_ids: list[str] = []
    for _asset_id, content_json, version_id in rows:
        try:
            value = json.loads(content_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        kind = value.get("kind")
        if kind not in grouped:
            continue
        version_ids.append(version_id)
        if kind == "concept":
            title = str(value.get("title") or "Concept")
            body = str(value.get("description") or "")
            rendered = f"### {title}\n\n{body}".rstrip()
            student_rendered = (
                f"### {html.escape(title, quote=False)}\n\n{html.escape(body, quote=False)}"
            ).rstrip()
        elif kind == "question":
            title = str(value.get("prompt") or "Question")
            answer = value.get("reference_answer")
            rubric = value.get("rubric")
            extra = ""
            if isinstance(answer, str) and answer:
                extra += f"\n\n#### Reference answer\n\n{answer}"
            if isinstance(rubric, dict):
                criteria = rubric.get("criteria")
                if isinstance(criteria, list) and criteria:
                    lines = ["\n\n#### Rubric"]
                    for criterion in criteria:
                        if isinstance(criterion, dict):
                            label = str(criterion.get("label") or "Criterion")
                            guidance = str(criterion.get("guidance") or "")
                            points = criterion.get("points", 0)
                            lines.append(f"\n- **{label}** ({points}): {guidance}".rstrip())
                    extra += "".join(lines)
            rendered = f"### {title}{extra}".rstrip()
            student_rendered = f"### {html.escape(title, quote=False)}"
        else:
            title = str(value.get("title") or "Note")
            body = str(value.get("body") or "")
            rendered = f"### {title}\n\n{body}".rstrip()
            student_rendered = (
                f"### {html.escape(title, quote=False)}\n\n{html.escape(body, quote=False)}"
            ).rstrip()
        grouped[kind].append(rendered)
        student_grouped[kind].append(student_rendered)

    full_sections = [f"# {name}"]
    student_sections = [f"# {name}"]
    labels = {"concept": "Concepts", "question": "Questions", "note": "Notes"}
    for kind in ("concept", "question", "note"):
        if grouped[kind]:
            full_sections.append(f"## {labels[kind]}\n\n" + "\n\n".join(grouped[kind]))
            student_sections.append(f"## {labels[kind]}\n\n" + "\n\n".join(student_grouped[kind]))
    return "\n\n".join(full_sections), "\n\n".join(student_sections)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # pysqlite can otherwise autocommit early SQLite DDL before its first
        # data write. Hold the migration's complete schema/backfill change in
        # one writer transaction so a failed backfill remains retryable.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.add_column(
        "knowledge_documents",
        sa.Column("content_version_seq", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=36),
            sa.ForeignKey("knowledge_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_seq", sa.Integer(), nullable=False),
        sa.Column(
            "stored_file_id",
            sa.String(length=36),
            sa.ForeignKey("stored_files.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("index_revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "version_seq", name="uq_knowledge_document_version_seq"),
        sa.CheckConstraint("version_seq >= 1", name="ck_knowledge_document_version_seq"),
        sa.CheckConstraint("char_count >= 1", name="ck_knowledge_document_version_char_count"),
        sa.CheckConstraint("index_revision >= 0", name="ck_knowledge_document_version_index"),
        sa.CheckConstraint("authorization_epoch >= 0", name="ck_knowledge_document_version_epoch"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_document_version_hash"),
        sa.CheckConstraint(
            "length(file_sha256) = 64", name="ck_knowledge_document_version_file_hash"
        ),
    )
    op.create_index(
        "ix_knowledge_document_versions_document",
        "knowledge_document_versions",
        ["document_id", "version_seq"],
    )
    op.add_column(
        "knowledge_sets",
        sa.Column("current_markdown_version_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_sets",
        sa.Column("generation_intent_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_generation_runs", sa.Column("action_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "knowledge_generation_runs",
        sa.Column("intent_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    bind.execute(
        sa.text("UPDATE knowledge_generation_runs SET action_id=id WHERE action_id IS NULL")
    )
    op.create_table(
        "knowledge_set_markdown_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "knowledge_set_id",
            sa.String(length=36),
            sa.ForeignKey("knowledge_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_seq", sa.Integer(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("student_projection_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("asset_version_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "generation_run_id",
            sa.String(length=36),
            sa.ForeignKey("knowledge_generation_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("generation_intent_seq", sa.Integer(), nullable=True),
        sa.Column("source_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "generator_agent_version_id",
            sa.String(length=36),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "knowledge_set_id", "version_seq", name="uq_knowledge_set_markdown_version_seq"
        ),
        sa.UniqueConstraint("generation_run_id", name="uq_knowledge_markdown_generation_run"),
        sa.CheckConstraint("version_seq >= 1", name="ck_knowledge_markdown_version_seq"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_markdown_hash"),
        sa.CheckConstraint(
            "origin IN ('manual', 'ai', 'legacy')", name="ck_knowledge_markdown_origin"
        ),
        sa.CheckConstraint(
            "generation_intent_seq IS NULL OR generation_intent_seq >= 0",
            name="ck_knowledge_markdown_intent_generation",
        ),
        sa.CheckConstraint(
            "source_manifest_hash IS NULL OR length(source_manifest_hash) = 64",
            name="ck_knowledge_markdown_source_hash",
        ),
    )
    op.create_index(
        "ix_knowledge_markdown_versions_set",
        "knowledge_set_markdown_versions",
        ["knowledge_set_id", "version_seq"],
    )
    op.create_index(
        "ix_knowledge_generation_set_action",
        "knowledge_generation_runs",
        ["knowledge_set_id", "action_id"],
        unique=True,
    )

    document_rows = bind.execute(
        sa.text(
            "SELECT d.id,d.source_filename,d.char_count,d.index_revision,d.content_hash,"
            "d.authorization_epoch,d.owner_user_id,d.created_at,d.stored_file_id,f.sha256 "
            "FROM knowledge_documents d JOIN stored_files f ON f.id=d.stored_file_id"
        )
    ).all()
    for (
        document_id,
        filename,
        char_count,
        index_revision,
        content_hash,
        authorization_epoch,
        owner_id,
        created_at,
        stored_file_id,
        file_sha256,
    ) in document_rows:
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_document_versions "
                "(id,document_id,version_seq,stored_file_id,source_filename,char_count,"
                "index_revision,content_hash,file_sha256,authorization_epoch,"
                "created_by_user_id,created_at) "
                "VALUES (:id,:document_id,1,:stored_file_id,:filename,:char_count,:index_revision,"
                ":content_hash,:file_sha256,:authorization_epoch,:owner_id,:created_at)"
            ),
            {
                "id": str(uuid4()),
                "document_id": document_id,
                "stored_file_id": stored_file_id,
                "filename": filename,
                "char_count": char_count,
                "index_revision": index_revision,
                "content_hash": content_hash,
                "file_sha256": file_sha256,
                "authorization_epoch": authorization_epoch,
                "owner_id": owner_id,
                "created_at": created_at,
            },
        )

    rows = bind.execute(
        sa.text(
            "SELECT s.id, s.display_name, s.owner_user_id, "
            "a.id, av.content_json, av.id "
            "FROM knowledge_sets s "
            "JOIN knowledge_assets a ON a.knowledge_set_id=s.id "
            "JOIN knowledge_asset_versions av ON av.asset_id=a.id "
            "AND av.version_seq=a.current_version_seq "
            "WHERE s.deleted_at IS NULL AND a.current_version_seq >= 1 "
            "ORDER BY s.id, a.kind, a.id"
        )
    ).all()
    grouped_rows: dict[str, list[tuple[str, str, str]]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for set_id, display_name, owner_id, asset_id, content_json, version_id in rows:
        grouped_rows.setdefault(set_id, []).append((asset_id, content_json, version_id))
        meta[set_id] = (display_name, owner_id)
    for set_id, assets in grouped_rows.items():
        display_name, owner_id = meta[set_id]
        markdown, student_projection = _markdown_for_legacy_assets(assets, display_name)
        version_id = str(uuid4())
        version_seq = 1
        created_at = bind.execute(sa.text("SELECT CURRENT_TIMESTAMP")).scalar_one()
        bind.execute(
            sa.text(
                "INSERT INTO knowledge_set_markdown_versions "
                "(id,knowledge_set_id,version_seq,markdown,student_projection_markdown,"
                "asset_version_ids_json,content_hash,origin,created_by_user_id,created_at) "
                "VALUES (:id,:set_id,:seq,:markdown,:projection,:asset_ids,:hash,'legacy',"
                ":owner,:at)"
            ),
            {
                "id": version_id,
                "set_id": set_id,
                "seq": version_seq,
                "markdown": markdown,
                "projection": student_projection,
                "asset_ids": json.dumps([row[2] for row in assets], separators=(",", ":")),
                "hash": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                "owner": owner_id,
                "at": created_at,
            },
        )
        bind.execute(
            sa.text("UPDATE knowledge_sets SET current_markdown_version_seq=:seq WHERE id=:set_id"),
            {"seq": version_seq, "set_id": set_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # Keep history guards and every SQLite schema change in the same writer
        # transaction so a refusal or later DDL failure leaves the revision intact.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.execute(sa.text("SELECT 1 FROM knowledge_document_versions LIMIT 1")).first():
        raise RuntimeError("Cannot remove version history for stable KnowledgeDocument IDs.")
    if bind.execute(
        sa.text("SELECT 1 FROM knowledge_set_markdown_versions WHERE origin != 'legacy' LIMIT 1")
    ).first():
        raise RuntimeError("Cannot remove authored Brainform Markdown history.")
    if bind.execute(
        sa.text(
            "SELECT 1 FROM knowledge_generation_runs WHERE action_id != id "
            "OR intent_generation != 0 LIMIT 1"
        )
    ).first():
        raise RuntimeError("Cannot remove distinct Brainform generation intents.")
    op.drop_index("ix_knowledge_generation_set_action", table_name="knowledge_generation_runs")
    op.drop_index(
        "ix_knowledge_markdown_versions_set", table_name="knowledge_set_markdown_versions"
    )
    op.drop_table("knowledge_set_markdown_versions")
    op.drop_column("knowledge_generation_runs", "intent_generation")
    op.drop_column("knowledge_generation_runs", "action_id")
    op.drop_column("knowledge_sets", "generation_intent_seq")
    op.drop_column("knowledge_sets", "current_markdown_version_seq")
    op.drop_index(
        "ix_knowledge_document_versions_document", table_name="knowledge_document_versions"
    )
    op.drop_table("knowledge_document_versions")
    op.drop_column("knowledge_documents", "content_version_seq")
