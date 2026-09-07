"""Closed, read-only validation for the next Wave's synthetic RAG set.

The fixture is deliberately independent of the application runtime.  It
defines the questions, mutable knowledge variants, evidence locations and
answer requirements before a real Provider run exists.  Later integration code
may adapt real turn/retrieval output to the small report mapping accepted by
``validate_report``; this module never performs ingestion, embedding,
retrieval, generation, network I/O or writes.

The validator is a deterministic structural check.  Correct and updated
conditions need every predeclared evidence item and every predeclared fact
alias group.  Disabled and irrelevant conditions need an explicit uncertainty
answer and may not repeat a fixture-only fact.  Known irrelevant evidence may
be cited when its identity and excerpt are valid; whether that citation and
the answer support the teaching question remains an independent semantic
review.  No opaque model judge or citation count can turn a missing evidence
row into a structural pass.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

FIXTURE_ROOT = Path(__file__).resolve().parent
MANIFEST_FILENAME = "manifest.json"
MANIFEST_HASH_FILENAME = "manifest.sha256"
AUDIT_SCHEMA_VERSION = "next_wave_rag_audit_v1"
MANIFEST_SCHEMA_VERSION = "next_wave_acceptance_manifest_v1"
QUESTION_SCHEMA_VERSION = "next_wave_rag_questions_v1"
RAG_CONDITIONS = ("correct", "disabled", "irrelevant", "updated")
LANGUAGES = ("en", "zh")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,127}$")
_SAFE_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")

ConditionName = Literal["correct", "disabled", "irrelevant", "updated"]
Language = Literal["en", "zh"]
SemanticVerdict = Literal["pending", "not_evaluable"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A safe fixture or report error with no answer/source payload."""

    code: str
    field: str | None = None


class FixtureValidationError(ValueError):
    """The predeclared manifest or corpus is not safe to use."""

    def __init__(self, message: str, *, issues: Sequence[ValidationIssue] = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    evidence_id: str
    corpus_path: str
    locator: str
    marker: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnswerPolicy:
    """Predeclared lexical answer range for one question/condition."""

    required_any_groups: tuple[tuple[str, ...], ...]
    forbidden_any: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    condition: ConditionName
    corpus_path: str | None
    retrieval_status: str
    expected_evidence: tuple[EvidenceSpec, ...]
    allowed_retrieved_evidence: tuple[str, ...]
    answer_policy: AnswerPolicy


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    question_id: str
    language: Language
    question: str
    fact_ids: tuple[str, ...]
    current_aliases: tuple[tuple[str, ...], ...]
    updated_aliases: tuple[tuple[str, ...], ...]
    conditions: Mapping[ConditionName, ConditionSpec]


@dataclass(frozen=True, slots=True)
class SessionSpec:
    session_id: str
    session_kind: Literal["shape", "fresh"]
    language: Language
    agent_count: int
    round_count: int
    expected_turns: int
    barrage_mode: Literal["with_barrage", "without_barrage"]
    eligible_turns: tuple[int, ...]
    barrage_ids: tuple[str, ...]
    expected_final_replies: int


@dataclass(frozen=True, slots=True)
class RAGCase:
    case_id: str
    question: QuestionSpec
    condition: ConditionSpec
    repeat: int


@dataclass(frozen=True, slots=True)
class ReportValidationResult:
    """Safe result for one report; answer and source text never leave this API."""

    case_id: str
    question_id: str
    condition: ConditionName
    repeat: int
    passed: bool
    error_codes: tuple[str, ...] = ()
    evidence_count: int = 0
    matched_fact_ids: tuple[str, ...] = ()
    answer_check: str = "semantic_review_required"
    review_warnings: tuple[str, ...] = ()
    # ``passed`` remains in the wire shape for old artifact readers, but this
    # validator never turns deterministic lexical/evidence checks into a
    # teaching-quality pass.  A structurally valid report is pending until an
    # independent semantic reviewer decides whether its answer is supported.
    human_review_required: bool = False
    structural_valid: bool = False
    semantic_verdict: SemanticVerdict = "not_evaluable"
    semantic_review_required: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "question_id": self.question_id,
            "condition": self.condition,
            "repeat": self.repeat,
            "passed": self.passed,
            "error_codes": list(self.error_codes),
            "evidence_count": self.evidence_count,
            "matched_fact_ids": list(self.matched_fact_ids),
            "answer_check": self.answer_check,
            "review_warnings": list(self.review_warnings),
            "human_review_required": self.human_review_required,
            "structural_valid": self.structural_valid,
            "semantic_verdict": self.semantic_verdict,
            "semantic_review_required": self.semantic_review_required,
        }


@dataclass(frozen=True, slots=True)
class AuditSummary:
    """Machine-readable, redacted plan or report audit."""

    status: str
    fixture_hash: str
    sessions_expected: int
    turns_expected: int
    classroom_reports_expected: int
    rag_answers_expected: int
    barrage_assignments: Mapping[str, int]
    rag_reports: tuple[ReportValidationResult, ...] = ()
    errors: tuple[str, ...] = ()
    real_execution_status: str = "pending_integration"
    execution_scope: str = "validator_only"
    pending_integrations: tuple[str, ...] = (
        "knowledge_import_publish",
        "snapshot_embedding",
        "query_embedding_retrieval",
        "turn_generation",
        "report_export",
    )

    @property
    def passed_reports(self) -> int:
        return sum(result.passed for result in self.rag_reports)

    @property
    def structurally_valid_reports(self) -> int:
        return sum(result.structural_valid for result in self.rag_reports)

    @property
    def semantic_pending_reports(self) -> int:
        return sum(result.semantic_verdict == "pending" for result in self.rag_reports)

    @property
    def semantic_verdict(self) -> SemanticVerdict:
        if self.semantic_pending_reports > 0 and self.failed_reports == 0:
            return "pending"
        return "not_evaluable"

    @property
    def failed_reports(self) -> int:
        return sum(not result.structural_valid for result in self.rag_reports)

    def as_dict(self) -> dict[str, object]:
        """Return only IDs, counts and safe codes; never answer/source payloads."""

        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "status": self.status,
            "fixture_hash": self.fixture_hash,
            "real_execution_status": self.real_execution_status,
            "execution_scope": self.execution_scope,
            "execution_observed": False,
            "real_calls_made": 0,
            "pending_integrations": list(self.pending_integrations),
            "sessions_expected": self.sessions_expected,
            "turns_expected": self.turns_expected,
            "classroom_reports_expected": self.classroom_reports_expected,
            "rag_answers_expected": self.rag_answers_expected,
            "rag_reports_seen": len(self.rag_reports),
            "rag_reports_passed": self.passed_reports,
            "rag_reports_failed": self.failed_reports,
            "rag_reports_structurally_valid": self.structurally_valid_reports,
            "semantic_pending_reports": self.semantic_pending_reports,
            "semantic_verdict": self.semantic_verdict,
            "semantic_review_required": self.semantic_pending_reports > 0,
            "human_review_required": self.semantic_pending_reports > 0,
            "barrage_assignments": dict(self.barrage_assignments),
            "errors": list(self.errors),
            "reports": [result.as_dict() for result in self.rag_reports],
        }


def _issue(code: str, field: str | None = None) -> FixtureValidationError:
    detail = code if field is None else f"{code}: {field}"
    return FixtureValidationError(detail, issues=(ValidationIssue(code, field),))


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _issue("fixture_object_required", field)
    return cast(Mapping[str, object], value)


def _string(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _issue("fixture_string_required", field)
    return value


def _integer(value: object, *, field: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _issue("fixture_integer_required", field)
    if minimum is not None and value < minimum:
        raise _issue("fixture_integer_out_of_range", field)
    return value


def _list(value: object, *, field: str) -> list[object]:
    if not isinstance(value, list):
        raise _issue("fixture_list_required", field)
    return value


def _safe_relative_path(value: object, *, field: str) -> str:
    path = _string(value, field=field)
    if not _SAFE_RELATIVE_PATH_RE.fullmatch(path) or path.startswith("."):
        raise _issue("fixture_path_invalid", field)
    return path


def _normalise(value: str) -> str:
    """Normalize presentation differences while preserving fact words."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def _contains(value: str, phrase: str) -> bool:
    return _normalise(phrase) in _normalise(value)


def _read_json(path: Path, *, field: str) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _issue("fixture_json_invalid", field) from exc
    return _mapping(value, field=field)


def _relative_fixture_file(root: Path, relative: str, *, field: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise _issue("fixture_path_outside_root", field) from exc
    if not candidate.is_file():
        raise _issue("fixture_file_missing", field)
    return candidate


def _parse_evidence(
    value: object,
    *,
    field: str,
    expected_path: str,
) -> tuple[EvidenceSpec, ...]:
    entries = _list(value, field=field)
    result: list[EvidenceSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        item = _mapping(raw, field=f"{field}[{index}]")
        evidence_id = _string(item.get("evidence_id"), field=f"{field}[{index}].evidence_id")
        if evidence_id in seen:
            raise _issue("fixture_duplicate_evidence_id", field)
        seen.add(evidence_id)
        corpus_path = _safe_relative_path(
            item.get("corpus_path"), field=f"{field}[{index}].corpus_path"
        )
        if corpus_path != expected_path:
            raise _issue("fixture_evidence_path_mismatch", field)
        locator = _string(item.get("locator"), field=f"{field}[{index}].locator")
        marker = _string(item.get("marker"), field=f"{field}[{index}].marker")
        raw_fact_ids = _list(item.get("fact_ids"), field=f"{field}[{index}].fact_ids")
        fact_ids = tuple(
            _string(fact_id, field=f"{field}[{index}].fact_ids[{fact_index}]")
            for fact_index, fact_id in enumerate(raw_fact_ids)
        )
        result.append(EvidenceSpec(evidence_id, corpus_path, locator, marker, fact_ids))
    return tuple(result)


def _parse_policy(value: object, *, field: str) -> AnswerPolicy:
    item = _mapping(value, field=field)
    raw_groups = _list(item.get("required_any_groups"), field=f"{field}.required_any_groups")
    groups: list[tuple[str, ...]] = []
    for index, raw_group in enumerate(raw_groups):
        values = _list(raw_group, field=f"{field}.required_any_groups[{index}]")
        if not values:
            raise _issue("fixture_answer_group_empty", field)
        groups.append(
            tuple(
                _string(value, field=f"{field}.required_any_groups[{index}][{value_index}]")
                for value_index, value in enumerate(values)
            )
        )
    forbidden = tuple(
        _string(value, field=f"{field}.forbidden_any[{index}]")
        for index, value in enumerate(
            _list(item.get("forbidden_any"), field=f"{field}.forbidden_any")
        )
    )
    if not groups:
        raise _issue("fixture_answer_policy_empty", field)
    return AnswerPolicy(tuple(groups), forbidden)


def _parse_question(raw: object, *, index: int) -> QuestionSpec:
    field = f"questions[{index}]"
    item = _mapping(raw, field=field)
    question_id = _string(item.get("question_id"), field=f"{field}.question_id")
    if not _CASE_ID_RE.fullmatch(question_id):
        raise _issue("fixture_id_invalid", f"{field}.question_id")
    language_value = _string(item.get("language"), field=f"{field}.language")
    if language_value not in LANGUAGES:
        raise _issue("fixture_language_invalid", field)
    language = cast(Language, language_value)
    question = _string(item.get("question"), field=f"{field}.question")
    raw_facts = _list(item.get("facts"), field=f"{field}.facts")
    fact_ids: list[str] = []
    current_aliases: list[tuple[str, ...]] = []
    updated_aliases: list[tuple[str, ...]] = []
    seen_fact_ids: set[str] = set()
    for fact_index, raw_fact in enumerate(raw_facts):
        fact_field = f"{field}.facts[{fact_index}]"
        fact = _mapping(raw_fact, field=fact_field)
        fact_id = _string(fact.get("fact_id"), field=f"{fact_field}.fact_id")
        if fact_id in seen_fact_ids:
            raise _issue("fixture_duplicate_fact_id", field)
        seen_fact_ids.add(fact_id)
        fact_ids.append(fact_id)
        current = tuple(
            _string(value, field=f"{fact_field}.current_aliases[{alias_index}]")
            for alias_index, value in enumerate(
                _list(fact.get("current_aliases"), field=f"{fact_field}.current_aliases")
            )
        )
        updated = tuple(
            _string(value, field=f"{fact_field}.updated_aliases[{alias_index}]")
            for alias_index, value in enumerate(
                _list(fact.get("updated_aliases"), field=f"{fact_field}.updated_aliases")
            )
        )
        if not current or not updated:
            raise _issue("fixture_fact_aliases_empty", fact_field)
        current_aliases.append(current)
        updated_aliases.append(updated)
    if not fact_ids:
        raise _issue("fixture_facts_empty", field)

    raw_conditions = _list(item.get("conditions"), field=f"{field}.conditions")
    conditions: dict[ConditionName, ConditionSpec] = {}
    for condition_index, raw_condition in enumerate(raw_conditions):
        condition_field = f"{field}.conditions[{condition_index}]"
        condition_item = _mapping(raw_condition, field=condition_field)
        condition_value = _string(
            condition_item.get("condition"), field=f"{condition_field}.condition"
        )
        if condition_value not in RAG_CONDITIONS:
            raise _issue("fixture_condition_invalid", condition_field)
        condition = cast(ConditionName, condition_value)
        if condition in conditions:
            raise _issue("fixture_duplicate_condition", field)
        raw_path = condition_item.get("corpus_path")
        if raw_path is None:
            corpus_path = None
        else:
            corpus_path = _safe_relative_path(raw_path, field=f"{condition_field}.corpus_path")
        retrieval_status = _string(
            condition_item.get("retrieval_status"),
            field=f"{condition_field}.retrieval_status",
        )
        expected_evidence = _parse_evidence(
            condition_item.get("expected_evidence"),
            field=f"{condition_field}.expected_evidence",
            expected_path=corpus_path or "",
        )
        allowed_raw = _list(
            condition_item.get("allowed_retrieved_evidence"),
            field=f"{condition_field}.allowed_retrieved_evidence",
        )
        allowed_retrieved = tuple(
            _string(value, field=f"{condition_field}.allowed_retrieved_evidence[{index}]")
            for index, value in enumerate(allowed_raw)
        )
        expected_evidence_ids = {item.evidence_id for item in expected_evidence}
        if (
            len(set(allowed_retrieved)) != len(allowed_retrieved)
            or set(allowed_retrieved) != expected_evidence_ids
        ):
            raise _issue("fixture_retrieved_evidence_set_invalid", condition_field)
        policy = _parse_policy(
            condition_item.get("answer_policy"), field=f"{condition_field}.answer_policy"
        )
        conditions[condition] = ConditionSpec(
            condition,
            corpus_path,
            retrieval_status,
            expected_evidence,
            allowed_retrieved,
            policy,
        )
    if set(conditions) != set(RAG_CONDITIONS):
        raise _issue("fixture_condition_set_invalid", field)
    return QuestionSpec(
        question_id,
        language,
        question,
        tuple(fact_ids),
        tuple(current_aliases),
        tuple(updated_aliases),
        conditions,
    )


def _validate_corpus(root: Path, question: QuestionSpec) -> None:
    all_fact_ids = set(question.fact_ids)
    expected_current = {
        _normalise(alias) for aliases in question.current_aliases for alias in aliases
    }
    expected_updated = {
        _normalise(alias) for aliases in question.updated_aliases for alias in aliases
    }
    uncertain_phrases = (
        ("no evidence", "not enough evidence", "cannot determine", "cannot answer")
        if question.language == "en"
        else ("没有足够证据", "无法确定", "无法回答", "资料不足")
    )
    for condition_name, condition in question.conditions.items():
        policy_groups = tuple(
            frozenset(_normalise(alias) for alias in group)
            for group in condition.answer_policy.required_any_groups
        )
        policy_forbidden = {_normalise(alias) for alias in condition.answer_policy.forbidden_any}
        if condition_name == "correct":
            expected_groups = tuple(
                frozenset(_normalise(alias) for alias in aliases)
                for aliases in question.current_aliases
            )
            if policy_groups != expected_groups or policy_forbidden != expected_updated:
                raise _issue("current_answer_policy_mismatch", question.question_id)
        elif condition_name == "updated":
            expected_groups = tuple(
                frozenset(_normalise(alias) for alias in aliases)
                for aliases in question.updated_aliases
            )
            if policy_groups != expected_groups or policy_forbidden != expected_current:
                raise _issue("updated_answer_policy_mismatch", question.question_id)
        else:
            if len(policy_groups) != 1 or not set(uncertain_phrases).intersection(policy_groups[0]):
                raise _issue("uncertainty_answer_policy_mismatch", question.question_id)
            if policy_forbidden != expected_current | expected_updated:
                raise _issue("no_match_answer_policy_mismatch", question.question_id)
        if condition_name == "disabled":
            if condition.corpus_path is not None or condition.expected_evidence:
                raise _issue("disabled_condition_has_corpus", question.question_id)
            continue
        if condition.corpus_path is None:
            raise _issue("corpus_path_missing", f"{question.question_id}.{condition_name}")
        corpus_file = _relative_fixture_file(
            root, condition.corpus_path, field=f"{question.question_id}.{condition_name}"
        )
        try:
            text = corpus_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise _issue("corpus_text_invalid", condition.corpus_path) from exc
        if "\x00" in text:
            raise _issue("corpus_text_invalid", condition.corpus_path)
        if condition_name == "irrelevant":
            if any(evidence.fact_ids for evidence in condition.expected_evidence):
                raise _issue("irrelevant_evidence_has_gold_fact", question.question_id)
        else:
            covered = {
                fact_id for evidence in condition.expected_evidence for fact_id in evidence.fact_ids
            }
            if covered != all_fact_ids:
                raise _issue(
                    "gold_fact_evidence_incomplete", f"{question.question_id}.{condition_name}"
                )
        for evidence in condition.expected_evidence:
            if evidence.evidence_id not in condition.allowed_retrieved_evidence:
                raise _issue("evidence_not_retrievable", evidence.evidence_id)
            lines = text.splitlines()
            marker_lines = [index for index, line in enumerate(lines) if evidence.marker in line]
            if len(marker_lines) != 1:
                raise _issue("evidence_marker_not_unique", evidence.evidence_id)
            locator_lines = [index for index, line in enumerate(lines) if evidence.locator in line]
            if len(locator_lines) != 1:
                raise _issue("evidence_locator_not_unique", evidence.evidence_id)
            if not evidence.locator.strip():
                raise _issue("evidence_locator_invalid", evidence.evidence_id)
            marker_line = marker_lines[0]
            locator_line = locator_lines[0]
            next_heading = next(
                (
                    index
                    for index in range(locator_line + 1, len(lines))
                    if lines[index].lstrip().startswith("#")
                ),
                len(lines),
            )
            if marker_line <= locator_line or marker_line >= next_heading:
                raise _issue("evidence_location_mismatch", evidence.evidence_id)
            if condition_name in {"correct", "updated"}:
                alias_groups = (
                    question.current_aliases
                    if condition_name == "correct"
                    else question.updated_aliases
                )
                for fact_id in evidence.fact_ids:
                    fact_index = question.fact_ids.index(fact_id)
                    if not any(
                        _contains(evidence.marker, alias) for alias in alias_groups[fact_index]
                    ):
                        raise _issue("evidence_fact_marker_mismatch", evidence.evidence_id)


def _parse_sessions(manifest: Mapping[str, object]) -> tuple[SessionSpec, ...]:
    plan = _mapping(manifest.get("session_plan"), field="session_plan")
    raw_sessions = _list(plan.get("sessions"), field="session_plan.sessions")
    result: list[SessionSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_sessions):
        field = f"session_plan.sessions[{index}]"
        item = _mapping(raw, field=field)
        session_id = _string(item.get("session_id"), field=f"{field}.session_id")
        if session_id in seen:
            raise _issue("duplicate_session_id", session_id)
        seen.add(session_id)
        kind_value = _string(item.get("session_kind"), field=f"{field}.session_kind")
        if kind_value not in {"shape", "fresh"}:
            raise _issue("session_kind_invalid", field)
        language_value = _string(item.get("language"), field=f"{field}.language")
        if language_value not in LANGUAGES:
            raise _issue("session_language_invalid", field)
        language = cast(Language, language_value)
        agents = _integer(item.get("agent_count"), field=f"{field}.agent_count", minimum=2)
        rounds = _integer(item.get("round_count"), field=f"{field}.round_count", minimum=2)
        expected_turns = _integer(
            item.get("expected_turns"), field=f"{field}.expected_turns", minimum=1
        )
        if expected_turns != agents * rounds:
            raise _issue("session_turn_count_mismatch", session_id)
        mode_value = _string(item.get("barrage_mode"), field=f"{field}.barrage_mode")
        if mode_value not in {"with_barrage", "without_barrage"}:
            raise _issue("barrage_mode_invalid", field)
        mode = cast(Literal["with_barrage", "without_barrage"], mode_value)
        eligible = tuple(
            _integer(value, field=f"{field}.eligible_turns[{turn_index}]", minimum=1)
            for turn_index, value in enumerate(
                _list(item.get("eligible_turns"), field=f"{field}.eligible_turns")
            )
        )
        if any(turn >= rounds for turn in eligible) or len(set(eligible)) != len(eligible):
            raise _issue("barrage_turn_invalid", session_id)
        barrage_ids = tuple(
            _string(value, field=f"{field}.barrage_ids[{barrage_index}]")
            for barrage_index, value in enumerate(
                _list(item.get("barrage_ids"), field=f"{field}.barrage_ids")
            )
        )
        expected_replies = _integer(
            item.get("expected_final_replies"),
            field=f"{field}.expected_final_replies",
            minimum=0,
        )
        if mode == "with_barrage":
            if not eligible or not barrage_ids or expected_replies != agents:
                raise _issue("barrage_assignment_incomplete", session_id)
        elif eligible or barrage_ids or expected_replies != 0:
            raise _issue("no_barrage_assignment_invalid", session_id)
        result.append(
            SessionSpec(
                session_id,
                cast(Literal["shape", "fresh"], kind_value),
                language,
                agents,
                rounds,
                expected_turns,
                mode,
                eligible,
                barrage_ids,
                expected_replies,
            )
        )
    return tuple(result)


def _parse_rag_cases(
    manifest: Mapping[str, object], questions: Mapping[str, QuestionSpec]
) -> tuple[RAGCase, ...]:
    plan = _mapping(manifest.get("rag_plan"), field="rag_plan")
    raw_rows = _list(plan.get("cases"), field="rag_plan.cases")
    result: list[RAGCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows):
        field = f"rag_plan.cases[{index}]"
        item = _mapping(raw, field=field)
        question_id = _string(item.get("question_id"), field=f"{field}.question_id")
        question = questions.get(question_id)
        if question is None:
            raise _issue("rag_question_unknown", question_id)
        condition_value = _string(item.get("condition"), field=f"{field}.condition")
        if condition_value not in RAG_CONDITIONS:
            raise _issue("rag_condition_unknown", field)
        condition_name = cast(ConditionName, condition_value)
        repeats = _list(item.get("repeats"), field=f"{field}.repeats")
        repeat_values = tuple(
            _integer(value, field=f"{field}.repeats[{repeat_index}]", minimum=1)
            for repeat_index, value in enumerate(repeats)
        )
        if repeat_values != (1, 2, 3):
            raise _issue("rag_repeat_set_invalid", field)
        for repeat in repeat_values:
            case_id = f"{question_id}-{condition_name}-r{repeat}"
            if case_id in seen:
                raise _issue("duplicate_rag_case_id", case_id)
            seen.add(case_id)
            result.append(RAGCase(case_id, question, question.conditions[condition_name], repeat))
    return tuple(result)


def _validate_manifest_counts(
    manifest: Mapping[str, object], sessions: Sequence[SessionSpec], cases: Sequence[RAGCase]
) -> None:
    plan = _mapping(manifest.get("session_plan"), field="session_plan")
    raw_agents = _list(plan.get("agent_counts"), field="session_plan.agent_counts")
    raw_rounds = _list(plan.get("round_counts"), field="session_plan.round_counts")
    raw_languages = _list(plan.get("languages"), field="session_plan.languages")
    if raw_agents != [2, 3, 4, 5] or raw_rounds != [2, 3, 4, 5] or raw_languages != ["en", "zh"]:
        raise _issue("session_shape_constraints_invalid", "session_plan")
    expected_sessions = _integer(
        plan.get("expected_sessions"), field="session_plan.expected_sessions", minimum=1
    )
    expected_turns = _integer(
        plan.get("expected_turns"), field="session_plan.expected_turns", minimum=1
    )
    expected_reports = _integer(
        plan.get("expected_reports"), field="session_plan.expected_reports", minimum=1
    )
    if len(sessions) != expected_sessions or len(sessions) != 37:
        raise _issue("session_count_mismatch", "session_plan.sessions")
    if (
        sum(session.expected_turns for session in sessions) != expected_turns
        or expected_turns != 412
    ):
        raise _issue("turn_count_mismatch", "session_plan.expected_turns")
    if expected_reports != 37:
        raise _issue("classroom_report_count_mismatch", "session_plan.expected_reports")
    shape = [session for session in sessions if session.session_kind == "shape"]
    fresh = [session for session in sessions if session.session_kind == "fresh"]
    expected_shape = {
        (agents, rounds, language)
        for agents in range(2, 6)
        for rounds in range(2, 6)
        for language in LANGUAGES
    }
    actual_shape = {(s.agent_count, s.round_count, s.language) for s in shape}
    if actual_shape != expected_shape or len(shape) != 32:
        raise _issue("shape_session_matrix_mismatch", "session_plan.sessions")
    if len(fresh) != 5 or any(
        session.agent_count != 2 or session.round_count != 2 for session in fresh
    ):
        raise _issue("fresh_session_matrix_mismatch", "session_plan.sessions")

    rag_plan = _mapping(manifest.get("rag_plan"), field="rag_plan")
    if _list(rag_plan.get("conditions"), field="rag_plan.conditions") != list(RAG_CONDITIONS):
        raise _issue("rag_condition_constraints_invalid", "rag_plan.conditions")
    if _list(rag_plan.get("repeats"), field="rag_plan.repeats") != [1, 2, 3]:
        raise _issue("rag_repeat_constraints_invalid", "rag_plan.repeats")
    expected_answers = _integer(
        rag_plan.get("expected_answers"), field="rag_plan.expected_answers", minimum=1
    )
    if expected_answers != 72 or len(cases) != expected_answers:
        raise _issue("rag_answer_count_mismatch", "rag_plan")
    question_ids = {case.question.question_id for case in cases}
    if len(question_ids) != 6:
        raise _issue("rag_question_count_mismatch", "rag_plan")
    if {case.condition.condition for case in cases} != set(RAG_CONDITIONS):
        raise _issue("rag_condition_matrix_mismatch", "rag_plan")
    if {case.repeat for case in cases} != {1, 2, 3}:
        raise _issue("rag_repeat_matrix_mismatch", "rag_plan")


def load_fixture_bundle(root: Path | None = None) -> FixtureBundle:
    """Load and validate the immutable manifest plus all synthetic corpora."""

    fixture_root = (root or FIXTURE_ROOT).resolve()
    manifest_path = fixture_root / MANIFEST_FILENAME
    manifest = _read_json(manifest_path, field=MANIFEST_FILENAME)
    schema_version = _string(manifest.get("schema_version"), field="schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise _issue("manifest_schema_version_invalid", "schema_version")
    try:
        fixture_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        recorded_hash = (fixture_root / MANIFEST_HASH_FILENAME).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise _issue("manifest_hash_unavailable", MANIFEST_HASH_FILENAME) from exc
    if not _SHA256_RE.fullmatch(recorded_hash) or recorded_hash != fixture_hash:
        raise _issue("manifest_hash_mismatch", MANIFEST_HASH_FILENAME)
    file_hashes = manifest.get("files_sha256")
    if not isinstance(file_hashes, dict) or len(file_hashes) != 19:
        raise _issue("fixture_files_manifest_invalid", "files_sha256")
    for name, expected_hash in file_hashes.items():
        path = _relative_fixture_file(fixture_root, name, field="files_sha256")
        if (
            not isinstance(expected_hash, str)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash
        ):
            raise _issue("fixture_file_hash_mismatch", name)

    questions_path = _safe_relative_path(manifest.get("questions_file"), field="questions_file")
    corpus_directory = _safe_relative_path(
        manifest.get("corpus_directory"), field="corpus_directory"
    )
    if corpus_directory != "corpus":
        raise _issue("corpus_directory_invalid", "corpus_directory")
    questions_document = _read_json(
        _relative_fixture_file(fixture_root, questions_path, field="questions_file"),
        field=questions_path,
    )
    if (
        _string(questions_document.get("schema_version"), field="questions.schema_version")
        != QUESTION_SCHEMA_VERSION
    ):
        raise _issue("questions_schema_version_invalid", "questions.schema_version")
    raw_questions = _list(questions_document.get("questions"), field="questions.questions")
    parsed_questions = tuple(
        _parse_question(raw, index=index) for index, raw in enumerate(raw_questions)
    )
    if len(parsed_questions) != 6:
        raise _issue("question_count_mismatch", "questions.questions")
    if sum(question.language == "en" for question in parsed_questions) != 3:
        raise _issue("english_question_count_mismatch", "questions.questions")
    if sum(question.language == "zh" for question in parsed_questions) != 3:
        raise _issue("chinese_question_count_mismatch", "questions.questions")
    question_map: dict[str, QuestionSpec] = {}
    all_aliases: set[str] = set()
    for question in parsed_questions:
        if question.question_id in question_map:
            raise _issue("duplicate_question_id", question.question_id)
        question_map[question.question_id] = question
        for aliases in (*question.current_aliases, *question.updated_aliases):
            for alias in aliases:
                normalized = _normalise(alias)
                if normalized in all_aliases:
                    raise _issue("gold_fact_alias_not_unique", question.question_id)
                all_aliases.add(normalized)
        _validate_corpus(fixture_root, question)

    sessions = _parse_sessions(manifest)
    expected_files = {questions_path} | {
        condition.corpus_path
        for question in parsed_questions
        for condition in question.conditions.values()
        if condition.corpus_path is not None
    }
    if set(file_hashes) != expected_files:
        raise _issue("fixture_files_manifest_invalid", "files_sha256")
    cases = _parse_rag_cases(manifest, question_map)
    _validate_manifest_counts(manifest, sessions, cases)
    return FixtureBundle(fixture_root, fixture_hash, manifest, parsed_questions, sessions, cases)


@dataclass(frozen=True, slots=True)
class FixtureBundle:
    root: Path
    fixture_hash: str
    manifest: Mapping[str, object]
    questions: tuple[QuestionSpec, ...]
    sessions: tuple[SessionSpec, ...]
    rag_cases: tuple[RAGCase, ...]

    @property
    def barrage_assignments(self) -> dict[str, int]:
        return {
            "with_barrage": sum(s.barrage_mode == "with_barrage" for s in self.sessions),
            "without_barrage": sum(s.barrage_mode == "without_barrage" for s in self.sessions),
        }

    def plan_summary(self) -> AuditSummary:
        return AuditSummary(
            status="fixtures_valid",
            fixture_hash=self.fixture_hash,
            sessions_expected=len(self.sessions),
            turns_expected=sum(session.expected_turns for session in self.sessions),
            classroom_reports_expected=37,
            rag_answers_expected=len(self.rag_cases),
            barrage_assignments=self.barrage_assignments,
        )

    def case(self, case_id: str) -> RAGCase | None:
        return next((case for case in self.rag_cases if case.case_id == case_id), None)


def _report_string(report: Mapping[str, object], field: str) -> str | None:
    value = report.get(field)
    return value if isinstance(value, str) else None


def _report_evidence_items(report: Mapping[str, object]) -> tuple[list[Mapping[str, object]], int]:
    raw = report.get("evidence")
    if not isinstance(raw, list):
        return [], 0
    valid = [cast(Mapping[str, object], item) for item in raw if isinstance(item, Mapping)]
    return valid, len(raw) - len(valid)


def _report_error(
    case: RAGCase,
    codes: Iterable[str],
    *,
    evidence_count: int = 0,
    matched_fact_ids: Iterable[str] = (),
    answer_check: str = "exact_aliases",
    review_warnings: Iterable[str] = (),
) -> ReportValidationResult:
    unique_codes = tuple(dict.fromkeys(codes))
    structural_valid = not unique_codes
    return ReportValidationResult(
        case_id=case.case_id,
        question_id=case.question.question_id,
        condition=case.condition.condition,
        repeat=case.repeat,
        # Mechanical checks are deliberately not a semantic pass.
        passed=False,
        error_codes=unique_codes,
        evidence_count=evidence_count,
        matched_fact_ids=tuple(matched_fact_ids),
        answer_check=answer_check,
        review_warnings=tuple(dict.fromkeys(review_warnings)),
        human_review_required=structural_valid,
        structural_valid=structural_valid,
        semantic_verdict="pending" if structural_valid else "not_evaluable",
        semantic_review_required=structural_valid,
    )


def validate_report(bundle: FixtureBundle, report: Mapping[str, object]) -> ReportValidationResult:
    """Validate one adapted RAG answer without mutating it or the fixture."""

    if not isinstance(report, Mapping):
        # Keep a stable case identity even when the caller supplied no object.
        return ReportValidationResult(
            case_id="unknown",
            question_id="unknown",
            condition="disabled",
            repeat=0,
            passed=False,
            error_codes=("report_object_required",),
        )
    case_id = _report_string(report, "case_id")
    case = bundle.case(case_id or "")
    if case is None:
        return ReportValidationResult(
            case_id=case_id or "unknown",
            question_id="unknown",
            condition="disabled",
            repeat=0,
            passed=False,
            error_codes=("unknown_case",),
        )
    errors: list[str] = []
    review_warnings: list[str] = []
    if _report_string(report, "question_id") != case.question.question_id:
        errors.append("question_id_mismatch")
    if _report_string(report, "condition") != case.condition.condition:
        errors.append("condition_mismatch")
    repeat_value = report.get("repeat")
    if (
        isinstance(repeat_value, bool)
        or not isinstance(repeat_value, int)
        or repeat_value != case.repeat
    ):
        errors.append("repeat_mismatch")
    answer = _report_string(report, "answer")
    if answer is None or not answer.strip():
        errors.append("answer_missing")
        answer = ""
    elif len(answer) > 20_000:
        errors.append("answer_too_large")
    retrieval_status = report.get("retrieval_status")
    if not isinstance(retrieval_status, str) or not retrieval_status:
        errors.append("retrieval_status_missing")
    elif case.condition.condition == "disabled" and retrieval_status != "no_match":
        errors.append("disabled_retrieval_status_invalid")
    elif case.condition.condition in {"correct", "updated"} and retrieval_status != "matched":
        errors.append("matched_retrieval_status_invalid")
    elif case.condition.condition == "irrelevant" and retrieval_status not in {
        "matched",
        "no_match",
    }:
        errors.append("irrelevant_retrieval_status_invalid")
    grounding_mode = report.get("grounding_mode")
    if not isinstance(grounding_mode, str) or not grounding_mode:
        errors.append("grounding_mode_missing")
    elif case.condition.condition in {"correct", "updated"} and grounding_mode not in {
        "rag_grounded",
        "mixed",
    }:
        errors.append("grounded_mode_invalid")
    elif case.condition.condition in {"disabled", "irrelevant"} and grounding_mode not in {
        "general_reasoning",
        "mixed",
    }:
        errors.append("general_mode_invalid")
    evidence_items, invalid_evidence_items = _report_evidence_items(report)
    raw_evidence = report.get("evidence")
    if raw_evidence is not None and not isinstance(raw_evidence, list):
        errors.append("evidence_shape_invalid")
    if invalid_evidence_items:
        errors.append("evidence_item_shape_invalid")
    evidence_ids: list[str] = []
    evidence_map = {evidence.evidence_id: evidence for evidence in case.condition.expected_evidence}
    allowed_ids = set(case.condition.allowed_retrieved_evidence)
    for item in evidence_items:
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            errors.append("evidence_id_missing")
            continue
        if evidence_id in evidence_ids:
            errors.append("duplicate_evidence")
            continue
        evidence_ids.append(evidence_id)
        if evidence_id not in allowed_ids:
            errors.append("evidence_id_not_predeclared")
            continue
        expected = evidence_map.get(evidence_id)
        if expected is None:
            # An irrelevant retrieval receipt may be listed in a private
            # retrieval field, but it cannot be used as public evidence.
            errors.append("unsupported_evidence")
            continue
        path_value = item.get("corpus_path", item.get("source_filename"))
        locator_value = item.get("locator", item.get("source_locator"))
        if path_value != expected.corpus_path or locator_value != expected.locator:
            errors.append("evidence_location_mismatch")
        if expected.corpus_path != case.condition.corpus_path:
            errors.append("evidence_snapshot_mismatch")
        observed_excerpt = item.get("observed_excerpt")
        if not isinstance(observed_excerpt, str) or not observed_excerpt.strip():
            errors.append("evidence_excerpt_missing")
        else:
            # An ID/path/heading supplied by the model is only a claim.  The
            # observed excerpt must be checked against the immutable fixture
            # sentence before the evidence can support a deterministic pass.
            try:
                corpus_text = (
                    (bundle.root / expected.corpus_path).resolve().read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError):
                corpus_text = ""
                errors.append("evidence_source_unreadable")
            if not corpus_text or not _contains(corpus_text, expected.marker):
                errors.append("evidence_source_changed")
            elif not _contains(observed_excerpt, expected.marker):
                errors.append("evidence_excerpt_mismatch")

    retrieved_raw = report.get("retrieved_evidence_ids")
    retrieved_ids: list[str] | None = None
    if retrieved_raw is not None:
        if not isinstance(retrieved_raw, list) or not all(
            isinstance(item, str) for item in retrieved_raw
        ):
            errors.append("retrieved_evidence_shape_invalid")
        else:
            retrieved_ids = cast(list[str], retrieved_raw)
            if any(item not in allowed_ids for item in retrieved_ids):
                errors.append("retrieved_evidence_not_predeclared")
            if any(item not in retrieved_ids for item in evidence_ids):
                errors.append("used_evidence_not_retrieved")
    else:
        errors.append("retrieval_observation_missing")

    for phrase in case.condition.answer_policy.forbidden_any:
        if _contains(answer, phrase):
            errors.append(
                "stale_fact" if case.condition.condition == "updated" else "unsupported_fact"
            )
    matched_fact_ids: list[str] = []
    for group_index, group in enumerate(case.condition.answer_policy.required_any_groups):
        if not any(_contains(answer, phrase) for phrase in group):
            # Alias lists are bounded machine checks for synthetic facts.  A
            # valid paraphrase needs the owner's independent teaching review;
            # it must not be rejected merely for lacking one exact phrase.
            review_warnings.append(
                "answer_alias_missing"
                if case.condition.condition in {"correct", "updated"}
                else "uncertainty_answer_requires_human_review"
            )
        elif case.condition.condition in {"correct", "updated"} and group_index < len(
            case.question.fact_ids
        ):
            matched_fact_ids.append(case.question.fact_ids[group_index])

    expected_ids = {evidence.evidence_id for evidence in case.condition.expected_evidence}
    if case.condition.condition in {"correct", "updated"}:
        if not expected_ids:
            errors.append("gold_evidence_not_predeclared")
        missing = expected_ids.difference(evidence_ids)
        if missing:
            errors.append("missing_evidence")
        if set(evidence_ids).difference(expected_ids):
            errors.append("unsupported_evidence")
        if retrieved_ids is not None and not expected_ids.issubset(set(retrieved_ids)):
            errors.append("retrieved_gold_evidence_missing")
    elif case.condition.condition == "disabled":
        if evidence_ids:
            errors.append("unsupported_evidence")
        if case.condition.condition == "disabled" and retrieved_ids:
            errors.append("disabled_retrieval_not_empty")
    answer_check = (
        "manual_review_required"
        if review_warnings and case.condition.condition in {"correct", "updated"}
        else "uncertainty_review_required"
        if review_warnings
        else "semantic_review_required"
    )
    return _report_error(
        case,
        errors,
        evidence_count=len(evidence_ids),
        matched_fact_ids=matched_fact_ids,
        answer_check=answer_check,
        review_warnings=review_warnings,
    )


def validate_reports(
    bundle: FixtureBundle, reports: Sequence[Mapping[str, object]]
) -> AuditSummary:
    """Validate a complete 72-answer batch and report missing/duplicate cases."""

    results: list[ReportValidationResult] = []
    seen: set[str] = set()
    errors: list[str] = []
    for report in reports:
        case_id = _report_string(report, "case_id") if isinstance(report, Mapping) else None
        if case_id is not None and case_id in seen:
            errors.append("duplicate_case")
        elif case_id is not None:
            seen.add(case_id)
        result = validate_report(bundle, report)
        results.append(result)
        if not result.passed:
            errors.extend(result.error_codes)
    expected_ids = {case.case_id for case in bundle.rag_cases}
    errors.extend("missing_case" for _ in expected_ids.difference(seen))
    errors.extend("unknown_case" for _ in seen.difference(expected_ids))
    errors = list(dict.fromkeys(errors))
    status = (
        "semantic_review_required"
        if len(results) == len(expected_ids) and not errors
        else "reports_failed"
    )
    return AuditSummary(
        status=status,
        fixture_hash=bundle.fixture_hash,
        sessions_expected=len(bundle.sessions),
        turns_expected=sum(session.expected_turns for session in bundle.sessions),
        classroom_reports_expected=37,
        rag_answers_expected=len(bundle.rag_cases),
        barrage_assignments=bundle.barrage_assignments,
        rag_reports=tuple(results),
        errors=tuple(errors),
    )


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "AuditSummary",
    "ConditionSpec",
    "EvidenceSpec",
    "FIXTURE_ROOT",
    "FixtureBundle",
    "FixtureValidationError",
    "QuestionSpec",
    "RAGCase",
    "ReportValidationResult",
    "SessionSpec",
    "load_fixture_bundle",
    "validate_report",
    "validate_reports",
]
