"""Remove rows with everything that points at them, by one explicit rule per foreign key.

Every foreign key into a table a hard delete removes has a rule in
``REFERENCE_RULES``:

- ``delete``: the referencing rows go too, and their own references are
  handled the same way;
- ``null``: the referencing columns are cleared and the row stays. Records,
  grades, answers, Debate copies and provider ledgers only ever get this;
- ``protect``: a referencing row keeps the parent, which then stays in place.

The rules run in code and never rely on the database's ON DELETE. Production
was created from older models, and some of its constraints are RESTRICT where
the models now say SET NULL (``provider_export_manifests.agent_version_id``).
Foreign keys are read from the live database, so a constraint only production
has is still seen. One without a rule keeps its parent and is logged;
``tests/test_purge_rules.py`` fails when a model foreign key has no rule.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import MetaData, Table, delete, inspect, select, text, tuple_, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

LOGGER = logging.getLogger(__name__)

Rule = Literal["delete", "null", "protect"]

# Keyed "child.col_a,col_b->parent" with the child's columns sorted.
REFERENCE_RULES: dict[str, Rule] = {
    "agent_account_memories.agent_id->agents": "delete",
    "agent_conversation_turns.conversation_id->agent_conversations": "delete",
    "agent_conversations.agent_version_id->agent_versions": "null",
    "agent_conversations.publication_id->course_team_publications": "null",
    "agent_conversations.snapshot_id->knowledge_snapshots": "null",
    "agent_conversations.team_id,team_version_id->team_versions": "null",
    "agent_conversations.team_id->teams": "null",
    "agent_edit_audit.agent_id->agents": "delete",
    "agent_knowledge_sets.agent_id->agents": "delete",
    "agent_knowledge_sets.knowledge_set_id->knowledge_sets": "delete",
    "agent_version_documents.agent_version_id->agent_versions": "delete",
    "agent_version_documents.document_id->knowledge_documents": "delete",
    "agent_versions.agent_id->agents": "delete",
    "assessment_activities.boundary_agent_version_id->agent_versions": "null",
    "assessment_activities.boundary_team_member_id,team_version_id->team_version_members": "null",
    "assessment_activities.evaluator_agent_version_id->agent_versions": "null",
    "assessment_activities.evaluator_team_member_id,team_version_id->team_version_members": "null",
    "assessment_activities.publication_id->course_team_publications": "null",
    "assessment_activities.recipe_version_id->agent_versions": "null",
    "assessment_activities.team_id,team_version_id->team_versions": "null",
    "assessment_activity_questions.asset_id,knowledge_set_id->knowledge_assets": "null",
    "assessment_activity_questions.question_version_id->knowledge_asset_versions": "null",
    "assessment_attempt_events.attempt_id,question_id->assessment_attempt_questions": "delete",
    "assessment_attempt_events.attempt_id->assessment_attempts": "delete",
    "assessment_attempt_events.learning_record_id->learning_records": "null",
    "assessment_attempt_events.replacement_attempt_id->assessment_attempts": "null",
    "assessment_attempt_questions.activity_id,attempt_id->assessment_attempts": "delete",
    "assessment_attempt_questions.effective_answer_record_id->learning_records": "null",
    "assessment_attempt_questions.question_version_id->knowledge_asset_versions": "null",
    "assessment_attempts.source_conversation_id->agent_conversations": "null",
    "assessment_course_report_evidence.attempt_id->assessment_attempts": "delete",
    "chat_memory_entry_actions.conversation_id->agent_conversations": "delete",
    "chat_provider_consent_bindings.conversation_id->agent_conversations": "delete",
    "chat_reports.conversation_id->agent_conversations": "delete",
    "conversation_attachments.conversation_id->agent_conversations": "delete",
    "conversation_participant_sets.knowledge_set_id->knowledge_sets": "delete",
    "conversation_participant_sets.participant_id->conversation_participants": "delete",
    "conversation_participants.agent_id->agents": "null",
    "conversation_participants.agent_version_id->agent_versions": "null",
    "conversation_participants.conversation_id,team_version_id->agent_conversations": "delete",
    "conversation_participants.invoke_grant_id->team_member_invoke_grants": "null",
    "conversation_participants.snapshot_id->knowledge_snapshots": "null",
    "conversation_participants.team_member_id,team_version_id->team_version_members": "null",
    "conversation_shared_sets.conversation_id->agent_conversations": "delete",
    "conversation_shared_sets.knowledge_set_id->knowledge_sets": "delete",
    "course_team_publications.team_id->teams": "delete",
    "course_team_publications.team_version_id->team_versions": "delete",
    "debate_participants.agent_id->agents": "null",
    "debate_participants.agent_version_id->agent_versions": "null",
    "debate_participants.effective_voice_profile_id->voice_profiles": "null",
    "debate_participants.knowledge_snapshot_id->knowledge_snapshots": "protect",
    "debate_participants.requested_voice_profile_id->voice_profiles": "null",
    "debate_turns.actual_tts_voice_profile_id->voice_profiles": "null",
    "debate_turns.audio_file_id->stored_files": "protect",
    "debate_voice_clones.sample_file_id->stored_files": "protect",
    "demo_acceptance_runs.baseline_agent_id->agents": "protect",
    "demo_acceptance_runs.baseline_snapshot_id->knowledge_snapshots": "protect",
    "demo_acceptance_runs.baseline_version_id->agent_versions": "protect",
    "demo_acceptance_runs.target_agent_id->agents": "protect",
    "demo_acceptance_runs.target_version_id->agent_versions": "protect",
    "file_references.stored_file_id->stored_files": "delete",
    "jobs.document_id->knowledge_documents": "delete",
    "knowledge_asset_version_sources.asset_version_id->knowledge_asset_versions": "delete",
    "knowledge_asset_version_sources.document_id->knowledge_documents": "null",
    "knowledge_asset_version_sources.source_binding_id->knowledge_set_sources": "delete",
    "knowledge_asset_version_sources.stored_file_id->stored_files": "protect",
    "knowledge_asset_versions.asset_id->knowledge_assets": "delete",
    "knowledge_asset_versions.generator_agent_version_id->agent_versions": "null",
    "knowledge_assets.knowledge_set_id->knowledge_sets": "delete",
    "knowledge_chunks.document_id,snapshot_document_id,snapshot_id->snapshot_documents": "delete",
    "knowledge_chunks.document_id->knowledge_documents": "null",
    "knowledge_chunks.snapshot_document_id->snapshot_documents": "delete",
    "knowledge_chunks.snapshot_id->knowledge_snapshots": "delete",
    "knowledge_document_chunks.document_id->knowledge_documents": "delete",
    "knowledge_document_versions.document_id->knowledge_documents": "delete",
    "knowledge_document_versions.stored_file_id->stored_files": "protect",
    "knowledge_documents.stored_file_id->stored_files": "protect",
    "knowledge_generation_accepted_stages.run_id->knowledge_generation_runs": "delete",
    "knowledge_generation_items.asset_id->knowledge_assets": "null",
    "knowledge_generation_items.asset_version_id->knowledge_asset_versions": "null",
    "knowledge_generation_items.run_id->knowledge_generation_runs": "delete",
    "knowledge_generation_runs.agent_id->agents": "null",
    "knowledge_generation_runs.agent_version_id->agent_versions": "null",
    "knowledge_generation_runs.job_id->jobs": "protect",
    "knowledge_generation_runs.knowledge_set_id->knowledge_sets": "delete",
    "knowledge_generation_source_receipts.document_id->knowledge_documents": "null",
    "knowledge_generation_source_receipts.run_id->knowledge_generation_runs": "delete",
    "knowledge_generation_source_receipts.source_binding_id->knowledge_set_sources": "delete",
    "knowledge_generation_source_receipts.stored_file_id->stored_files": "protect",
    "knowledge_generation_target_snapshots.run_id->knowledge_generation_runs": "delete",
    "knowledge_set_markdown_versions.generation_run_id->knowledge_generation_runs": "null",
    "knowledge_set_markdown_versions.generator_agent_version_id->agent_versions": "null",
    "knowledge_set_markdown_versions.knowledge_set_id->knowledge_sets": "delete",
    "knowledge_set_sources.document_id->knowledge_documents": "null",
    "knowledge_set_sources.knowledge_set_id->knowledge_sets": "delete",
    "knowledge_set_sources.stored_file_id->stored_files": "protect",
    "knowledge_snapshots.agent_version_id->agent_versions": "null",
    "knowledge_snapshots.combined_file_id->stored_files": "protect",
    "learning_assessment_mutations.assessment_id,revision_id->learning_assessment_revisions": "delete",  # noqa: E501
    "learning_assessment_mutations.assessment_id->learning_assessments": "delete",
    "learning_assessment_mutations.conversation_id->agent_conversations": "null",
    "learning_assessment_resource_grants.agent_version_id->agent_versions": "null",
    "learning_assessment_resource_grants.assessment_id->learning_assessments": "delete",
    "learning_assessment_resource_grants.conversation_id,participant_id->conversation_participants": "null",  # noqa: E501
    "learning_assessment_resource_grants.conversation_id->agent_conversations": "null",
    "learning_assessment_resource_grants.team_member_id->team_version_members": "null",
    "learning_assessment_revisions.assessment_id,previous_revision_id->learning_assessment_revisions": "delete",  # noqa: E501
    "learning_assessment_revisions.assessment_id->learning_assessments": "delete",
    "learning_assessment_revisions.conversation_id->agent_conversations": "null",
    "learning_assessment_revisions.team_id,team_version_id->team_versions": "null",
    "learning_assessments.created_conversation_id->agent_conversations": "null",
    "learning_boundaries.attempt_id->assessment_attempts": "delete",
    "learning_boundaries.conversation_id->agent_conversations": "null",
    # Evidence keeps exactly one source (XOR CHECK). Nulling a source on a
    # staying row fails that CHECK; teacher Record delete must remove the row.
    "learning_boundary_evidence.assessment_revision_id->learning_assessment_revisions": "delete",
    "learning_boundary_evidence.attempt_id,boundary_revision_id->learning_boundary_revisions": "delete",  # noqa: E501
    "learning_boundary_evidence.learning_record_id->learning_records": "delete",
    "learning_boundary_revisions.attempt_id,boundary_id->learning_boundaries": "delete",
    "learning_boundary_revisions.boundary_id,previous_revision_id->learning_boundary_revisions": "delete",  # noqa: E501
    "learning_boundary_revisions.summarizer_agent_version_id->agent_versions": "null",
    "learning_boundary_revisions.summarizer_team_member_id->team_version_members": "null",
    "learning_records.attempt_id->assessment_attempts": "delete",
    "learning_records.conversation_id->agent_conversations": "null",
    "learning_records.team_id,team_version_id->team_versions": "null",
    "provider_export_manifests.agent_version_id->agent_versions": "null",
    "runtime_model_call_stages.conversation_id->agent_conversations": "delete",
    "runtime_model_call_stages.executor_agent_version_id->agent_versions": "null",
    "runtime_model_call_stages.turn_id->agent_conversation_turns": "delete",
    "runtime_tool_receipts.conversation_id->agent_conversations": "delete",
    "runtime_tool_receipts.turn_id->agent_conversation_turns": "delete",
    "snapshot_documents.document_id->knowledge_documents": "null",
    "snapshot_documents.frozen_file_id->stored_files": "protect",
    "snapshot_documents.snapshot_id->knowledge_snapshots": "delete",
    "team_chat_events.conversation_id->agent_conversations": "delete",
    "team_chat_events.result_id->team_turn_results": "delete",
    "team_chat_events.turn_id->agent_conversation_turns": "delete",
    "team_member_invoke_grants.agent_id->agents": "null",
    "team_member_invoke_grants.agent_version_id->agent_versions": "null",
    "team_member_invoke_grants.publication_id->course_team_publications": "delete",
    "team_member_invoke_grants.team_member_id->team_version_members": "delete",
    "team_member_invoke_grants.team_version_id->team_versions": "delete",
    "team_provider_calls.result_id->team_turn_results": "delete",
    "team_provider_consent_bindings.result_id->team_turn_results": "delete",
    "team_provider_consent_bindings.standing_grant_id->team_provider_standing_grants": "null",
    "team_provider_standing_grants.publication_id->course_team_publications": "delete",
    "team_provider_standing_grants.team_id->teams": "delete",
    "team_provider_standing_grants.team_version_id->team_versions": "delete",
    "team_turn_results.conversation_id,participant_id->conversation_participants": "delete",
    "team_turn_results.conversation_id,turn_id->agent_conversation_turns": "delete",
    "team_version_members.agent_id->agents": "null",
    "team_version_members.agent_version_id->agent_versions": "null",
    "team_version_members.team_version_id->team_versions": "delete",
    "team_version_sets.knowledge_set_id->knowledge_sets": "null",
    "team_version_sets.team_version_id->team_versions": "delete",
    "team_versions.team_id->teams": "delete",
    "turn_sources.chunk_id,snapshot_id->knowledge_chunks": "protect",
    "voice_previews.profile_id->voice_profiles": "delete",
    "voice_previews.stored_file_id->stored_files": "null",
    "voice_profiles.sample_file_id->stored_files": "protect",
    "voice_provider_operations.profile_id->voice_profiles": "delete",
}

# Tables a hard delete starts from. ``assessment_attempts`` and
# ``learning_assessments`` are only removed by a teacher's Record delete; the
# cleanup roots never reach them.
CLEANUP_ROOTS = (
    "agents",
    "agent_versions",
    "teams",
    "agent_conversations",
    "knowledge_documents",
    "knowledge_sets",
    "voice_profiles",
    "knowledge_snapshots",
    "stored_files",
)
RECORD_ROOTS = ("assessment_attempts", "learning_assessments")

_CHUNK = 500


@dataclass(frozen=True)
class ForeignKey:
    child: str
    columns: tuple[str, ...]
    parent: str
    referred: tuple[str, ...]
    nullable: tuple[bool, ...]

    @property
    def key(self) -> str:
        return f"{self.child}.{','.join(sorted(self.columns))}->{self.parent}"


_catalogs: dict[int, dict[str, list[ForeignKey]]] = {}
_catalog_lock = threading.Lock()


def _catalog(engine: Engine) -> dict[str, list[ForeignKey]]:
    """Incoming foreign keys per table, read once per engine from the database."""

    with _catalog_lock:
        cached = _catalogs.get(id(engine))
        if cached is not None:
            return cached
        catalog = read_foreign_key_catalog(engine)
        _catalogs[id(engine)] = catalog
        return catalog


# One query for every foreign key of the current schema, in the order the
# inspector reported them (table name, then constraint name). The first hard
# delete of a process used to inspect ~120 tables one by one: production saw
# ~2000 statements on the first Debate delete after a restart.
_FOREIGN_KEYS_SQL = text(
    """
    SELECT child.relname AS child, parent.relname AS parent,
           array_agg(a.attname ORDER BY k.ord) AS columns,
           array_agg(pa.attname ORDER BY k.ord) AS referred,
           array_agg(NOT a.attnotnull ORDER BY k.ord) AS nullable
    FROM pg_constraint AS c
    JOIN pg_class AS child ON child.oid = c.conrelid
    JOIN pg_namespace AS ns ON ns.oid = child.relnamespace
    JOIN pg_class AS parent ON parent.oid = c.confrelid
    CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(attnum, refnum, ord)
    JOIN pg_attribute AS a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
    JOIN pg_attribute AS pa ON pa.attrelid = c.confrelid AND pa.attnum = k.refnum
    WHERE c.contype = 'f' AND ns.nspname = current_schema() AND child.relkind IN ('r', 'p')
    GROUP BY c.oid, c.conname, child.relname, parent.relname
    ORDER BY child.relname, c.conname
    """
)


def read_foreign_key_catalog(engine: Engine) -> dict[str, list[ForeignKey]]:
    """Incoming foreign keys per parent table, straight from pg_constraint."""

    incoming: dict[str, list[ForeignKey]] = defaultdict(list)
    with engine.connect() as connection:
        for row in connection.execute(_FOREIGN_KEYS_SQL).mappings():
            incoming[str(row["parent"])].append(
                ForeignKey(
                    child=str(row["child"]),
                    columns=tuple(row["columns"]),
                    parent=str(row["parent"]),
                    referred=tuple(row["referred"]),
                    nullable=tuple(bool(value) for value in row["nullable"]),
                )
            )
    return dict(incoming)


def reset_catalog_cache() -> None:
    with _catalog_lock:
        _catalogs.clear()


class _Purge:
    def __init__(self, db: Session) -> None:
        self.db = db
        bind = db.get_bind()
        engine = bind if isinstance(bind, Engine) else bind.engine
        self.catalog = _catalog(engine)
        self.tables: dict[str, Table] = {}
        self.deleted: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
        # Rows already deleted from the database (a subset of ``deleted``).
        self.removed: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
        self.updated: set[str] = set()
        self.warned: set[str] = set()

    def table(self, name: str) -> Table:
        found = self.tables.get(name)
        if found is None:
            from app.core.db import registered_metadata

            found = registered_metadata().tables.get(name)
            if found is None:
                # A table only this database has (an old migration's).
                found = Table(name, MetaData(), autoload_with=self.db.connection())
            self.tables[name] = found
        return found

    def pk(self, name: str) -> tuple[str, ...]:
        return tuple(column.name for column in self.table(name).primary_key.columns)

    def needed(self, name: str) -> list[str]:
        columns = list(self.pk(name))
        for foreign_key in self.catalog.get(name, []):
            columns.extend(column for column in foreign_key.referred if column not in columns)
        return columns

    def rule(self, foreign_key: ForeignKey) -> Rule:
        rule = REFERENCE_RULES.get(foreign_key.key)
        if rule is None:
            if foreign_key.key not in self.warned:
                self.warned.add(foreign_key.key)
                LOGGER.warning("purge_unknown_reference fk=%s", foreign_key.key)
            return "protect"
        if rule == "null" and not all(foreign_key.nullable):
            # A column the database will not clear cannot be released.
            return "protect"
        return rule

    def select_rows(self, name: str, where: ColumnElement[bool]) -> list[dict[str, Any]]:
        table = self.table(name)
        columns = [table.c[column] for column in self.needed(name)]
        return [dict(row._mapping) for row in self.db.execute(select(*columns).where(where))]

    def children(
        self, foreign_key: ForeignKey, parents: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        values = sorted(
            {tuple(row[column] for column in foreign_key.referred) for row in parents},
            key=repr,
        )
        child = self.table(foreign_key.child)
        found: list[dict[str, Any]] = []
        needed = list(dict.fromkeys([*self.needed(foreign_key.child), *foreign_key.columns]))
        for start in range(0, len(values), _CHUNK):
            chunk = values[start : start + _CHUNK]
            condition = _matches(child, foreign_key.columns, chunk)
            found.extend(
                dict(row._mapping)
                for row in self.db.execute(
                    select(*[child.c[column] for column in needed]).where(condition)
                )
            )
        return found

    def blocked(
        self, name: str, rows: Sequence[dict[str, Any]], visiting: set[tuple[str, Any]]
    ) -> set[tuple[Any, ...]]:
        """Primary keys among ``rows`` that a protected reference keeps."""

        pk = self.pk(name)
        kept: set[tuple[Any, ...]] = set()
        for foreign_key in self.catalog.get(name, []):
            rule = self.rule(foreign_key)
            if rule == "null":
                continue
            children = self.children(foreign_key, rows)
            if not children:
                continue
            if rule == "delete":
                child_pk = self.pk(foreign_key.child)
                fresh = [
                    child
                    for child in children
                    if (foreign_key.child, tuple(child[c] for c in child_pk)) not in visiting
                ]
                visiting.update(
                    (foreign_key.child, tuple(child[c] for c in child_pk)) for child in fresh
                )
                kept_children = self.blocked(foreign_key.child, fresh, visiting) if fresh else set()
                children = [
                    child for child in fresh if tuple(child[c] for c in child_pk) in kept_children
                ]
            referenced = {
                tuple(child[column] for column in foreign_key.columns) for child in children
            }
            for row in rows:
                if tuple(row[column] for column in foreign_key.referred) in referenced:
                    kept.add(tuple(row[column] for column in pk))
        return kept

    def remove(self, name: str, rows: Sequence[dict[str, Any]]) -> int:
        """Delete ``rows`` and everything a delete rule reaches from them.

        Two phases: first the whole delete set is planned, then references
        that a null rule releases are cleared only on rows that stay, and the
        planned rows are deleted children first. Clearing a reference on a row
        that is about to go anyway could break its own CHECK (an answered
        question must keep its answer) before the row is deleted.
        """

        self.null_jobs: list[tuple[ForeignKey, set[tuple[Any, ...]]]] = []
        self.self_clears: list[tuple[str, list[str], set[tuple[Any, ...]]]] = []
        self.order: list[str] = []
        before = set(self.deleted[name])
        self.plan(name, rows)
        self.clear_released_references()
        self.delete_planned()
        return len(self.deleted[name] - before)

    def plan(self, name: str, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        pk = self.pk(name)
        keys = {tuple(row[column] for column in pk) for row in rows} - self.deleted[name]
        rows = [row for row in rows if tuple(row[column] for column in pk) in keys]
        if not rows:
            return
        # Claimed first so a reference cycle back to these rows stops here.
        self.deleted[name].update(keys)
        if name not in self.order:
            self.order.append(name)
        for foreign_key in self.catalog.get(name, []):
            rule = self.rule(foreign_key)
            if rule == "protect":
                continue
            if rule == "null":
                values = {tuple(row[c] for c in foreign_key.referred) for row in rows}
                self.null_jobs.append((foreign_key, values))
                continue
            if foreign_key.child == name:
                # Rows in this set that point at each other: clear the link first.
                nullable = [
                    column
                    for column, can_null in zip(
                        foreign_key.columns, foreign_key.nullable, strict=True
                    )
                    if can_null
                ]
                if nullable:
                    self.self_clears.append((name, nullable, keys))
            self.plan(foreign_key.child, self.children(foreign_key, rows))

    def clear_released_references(self) -> None:
        for name, nullable, keys in self.self_clears:
            self.updated.add(name)
            child = self.table(name)
            for chunk in _chunks(sorted(keys, key=repr)):
                self.db.execute(
                    update(child)
                    .where(_matches(child, self.pk(name), chunk))
                    .values({column: None for column in nullable})
                )
        for foreign_key, values in self.null_jobs:
            child = self.table(foreign_key.child)
            child_pk = self.pk(foreign_key.child)
            going = self.deleted.get(foreign_key.child, set())
            staying: list[tuple[Any, ...]] = []
            for chunk in _chunks(sorted(values, key=repr)):
                for row in self.db.execute(
                    select(*[child.c[column] for column in child_pk]).where(
                        _matches(child, foreign_key.columns, chunk)
                    )
                ):
                    key = tuple(row)
                    if key not in going:
                        staying.append(key)
            if not staying:
                continue
            self.updated.add(foreign_key.child)
            for chunk in _chunks(sorted(set(staying), key=repr)):
                self.db.execute(
                    update(child)
                    .where(_matches(child, child_pk, chunk))
                    .values({column: None for column in foreign_key.columns})
                )

    def delete_planned(self) -> None:
        """Delete every planned row, a referencing table before the table it names."""

        planned = [name for name in self.order if self.deleted.get(name)]
        waiting = {
            name: {
                foreign_key.child
                for foreign_key in self.catalog.get(name, [])
                if foreign_key.child != name and foreign_key.child in planned
            }
            for name in planned
        }
        done: set[str] = set()
        sequence: list[str] = []
        while len(sequence) < len(planned):
            ready = [name for name in planned if name not in done and not (waiting[name] - done)]
            if not ready:
                # A cycle (courses <-> debates): newest discoveries first.
                ready = [next(name for name in reversed(planned) if name not in done)]
            for name in ready:
                done.add(name)
                sequence.append(name)
        for name in sequence:
            table = self.table(name)
            keys = self.deleted[name] - self.removed[name]
            self.removed[name].update(keys)
            for chunk in _chunks(sorted(keys, key=repr)):
                self.db.execute(delete(table).where(_matches(table, self.pk(name), chunk)))

    def sync_session(self) -> None:
        """Forget deleted rows and reload what the SQL changed underneath the session."""

        touched = set(self.deleted) | self.updated
        for instance in list(self.db.identity_map.values()):
            state: Any = inspect(instance)
            if state.deleted or state.was_deleted:
                continue
            name = getattr(state.mapper.local_table, "name", None)
            identity = state.identity
            if name in self.deleted and identity is not None:
                if tuple(identity) in self.deleted[name]:
                    self.db.expunge(instance)
                    continue
            if name in touched:
                self.db.expire(instance)
                continue
            stale = [
                relationship.key
                for relationship in state.mapper.relationships
                if getattr(relationship.mapper.local_table, "name", None) in self.deleted
            ]
            if stale:
                self.db.expire(instance, stale)


def _chunks(values: Sequence[tuple[Any, ...]]) -> Iterable[Sequence[tuple[Any, ...]]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def _matches(
    table: Table, columns: Sequence[str], values: Sequence[tuple[Any, ...]]
) -> ColumnElement[bool]:
    if len(columns) == 1:
        return table.c[columns[0]].in_([value[0] for value in values])
    return tuple_(*[table.c[column] for column in columns]).in_(list(values))


def purge(db: Session, table_name: str, where: ColumnElement[bool]) -> set[tuple[Any, ...]]:
    """Delete the rows of ``table_name`` matching ``where`` unless something protected
    still points at them. Returns the primary keys that were deleted.
    """

    db.flush()
    work = _Purge(db)
    rows = work.select_rows(table_name, where)
    if not rows:
        return set()
    pk = work.pk(table_name)
    visiting = {(table_name, tuple(row[c] for c in pk)) for row in rows}
    kept = work.blocked(table_name, rows, visiting)
    if kept:
        LOGGER.info("purge_kept table=%s rows=%d", table_name, len(kept))
    work.remove(table_name, [row for row in rows if tuple(row[c] for c in pk) not in kept])
    deleted = set(work.deleted.get(table_name, set()))
    work.sync_session()
    return deleted


def purge_ids(db: Session, table_name: str, ids: Iterable[str]) -> set[str]:
    """``purge`` by a single-column primary key; returns the ids deleted."""

    wanted = [value for value in dict.fromkeys(ids) if value]
    if not wanted:
        return set()
    work_table = _Purge(db).table(table_name)
    (pk_column,) = work_table.primary_key.columns
    deleted: set[str] = set()
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start : start + _CHUNK]
        deleted.update(str(key[0]) for key in purge(db, table_name, pk_column.in_(chunk)))
    return deleted
