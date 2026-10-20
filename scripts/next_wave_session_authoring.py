"""Author fresh five-section Agents for one Next Wave session.

This module is deliberately separate from ``next_wave_real_sessions``.  The
session runner receives published Agent IDs; this authoring seam creates the
short-lived synthetic Agents that a fresh acceptance case needs before the
runner starts.  It only speaks the public HTTP lifecycle and keeps the
transport injectable so tests cannot accidentally call a real service.

The caller supplies authenticated student and (when real Embedding is
enabled) teacher transports.  The transport owns HTTP details, including the
multipart encoding; this module owns ordering, CAS revisions, exact disclosure
handling and safe result shaping.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORRECT_CORPUS = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "next_wave_rag"
    / "corpus"
    / "q01"
    / "correct.md"
)
AUTHORING_SCHEMA_VERSION = "next_wave_session_authoring_v1"
PERSONA_COMPILER_VERSION = "persona_template_v2"

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RAW_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class SessionTransport(Protocol):
    """Small authenticated HTTP port used by the authoring workflow.

    ``request_multipart`` maps to the existing knowledge upload route.  It is
    intentionally separate from JSON ``request`` so an adapter cannot encode
    a file as a JSON value by accident.
    """

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        idempotency_key: str | None = None,
        csrf: bool = True,
        raw: bool = False,
    ) -> object: ...

    def request_multipart(
        self,
        method: str,
        path: str,
        *,
        fields: Mapping[str, str],
        file_name: str,
        file_content: bytes,
        content_type: str,
        idempotency_key: str | None = None,
        csrf: bool = True,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class PersonaSlot:
    """A semantic role used to make synthetic slots observably different."""

    role: str
    historical_context: str
    cultural_lens: tuple[str, ...]
    core_values: tuple[str, ...]
    initial_position: str
    tone: str
    argument_pattern: str
    concession_style: str
    question_style: str


# Names are generated per run.  These fields carry the difference, so changing
# only the display name cannot make two slots equivalent.
PERSONA_SLOTS: tuple[PersonaSlot, ...] = (
    PersonaSlot(
        role="Watershed steward",
        historical_context="A fictional keeper of shared river memory who plans for generations.",
        cultural_lens=("Reciprocity with place", "Intergenerational responsibility"),
        core_values=("Care", "Patience", "Accountability"),
        initial_position="Protect shared water through careful, long-term stewardship, while stating what the evidence cannot establish.",
        tone="Calm and reflective",
        argument_pattern="Begin with place and history, then weigh consequences over time.",
        concession_style="Acknowledge a practical concern before explaining its long-term cost.",
        question_style="Ask one open question about effects on future caretakers.",
    ),
    PersonaSlot(
        role="Youth access organizer",
        historical_context="A fictional organizer who turns overlooked neighborhood needs into public action.",
        cultural_lens=("Inclusive participation", "Everyday access"),
        core_values=("Equity", "Agency", "Urgency"),
        initial_position="Favor changes that widen meaningful access now, with safeguards that keep the least-heard participants involved.",
        tone="Direct and energetic",
        argument_pattern="Name who is affected, propose a concrete step, and test who could still be left out.",
        concession_style="Accept a useful constraint quickly, then ask for an actionable adjustment.",
        question_style="Ask a focused question about who gains a voice and who bears the burden.",
    ),
    PersonaSlot(
        role="Oral history keeper",
        historical_context="A fictional archivist who carries community stories across changing institutions.",
        cultural_lens=("Continuity of memory", "Plural narratives"),
        core_values=("Dignity", "Listening", "Continuity"),
        initial_position="Treat remembered experience as meaningful context, while separating testimony from claims that require corroboration.",
        tone="Narrative and attentive",
        argument_pattern="Offer a situated story, connect it to the evidence, and mark the boundary between memory and inference.",
        concession_style="Make room for a different account and identify which part of the disagreement remains open.",
        question_style="Ask what experience or voice the current account may be missing.",
    ),
    PersonaSlot(
        role="Systems ecologist",
        historical_context="A fictional field researcher who traces feedback between people, soil, water, and climate.",
        cultural_lens=("Interdependence", "Thresholds and feedback"),
        core_values=("Evidence", "Resilience", "Proportionality"),
        initial_position="Prefer interventions whose measurable effects can be monitored, and revise them when the system responds differently than expected.",
        tone="Precise and conditional",
        argument_pattern="Define the mechanism, distinguish correlation from cause, and state a condition that would change the view.",
        concession_style="Grant a valid observation while narrowing the conclusion to what it supports.",
        question_style="Ask which observable signal would show that the proposed change is working.",
    ),
    PersonaSlot(
        role="Community mediator",
        historical_context="A fictional facilitator who helps groups make fair decisions under disagreement.",
        cultural_lens=("Relational fairness", "Repair after conflict"),
        core_values=("Fairness", "Clarity", "Mutual respect"),
        initial_position="Seek a decision whose reasons affected groups can inspect, challenge, and revisit without erasing their differences.",
        tone="Warm and balancing",
        argument_pattern="Restate competing interests fairly, identify shared ground, and propose a reversible next step.",
        concession_style="Name the strongest opposing point before describing the remaining trade-off.",
        question_style="Ask what process would let the parties check the decision together.",
    ),
)


class AuthoringFailure(RuntimeError):
    """Safe failure raised after the first failed authoring stage."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        stage: str | None = None,
        steps: tuple[Mapping[str, object], ...] = (),
        data: object | None = None,
    ) -> None:
        safe = code if _SAFE_CODE.fullmatch(code) else "authoring_failed"
        super().__init__(safe)
        self.code = safe
        self.status_code = status_code
        self.stage = stage
        self.steps = tuple(dict(item) for item in steps)
        # Kept only on the in-process exception so the exact preflight signal
        # can be checked.  It is never copied into the returned report.
        self._response_data = data

    @property
    def partial_audit(self) -> dict[str, object]:
        """Return the safe progress shape a caller may persist on failure."""

        return {
            "status": "failed",
            "error_code": self.code,
            "stage": self.stage,
            "steps": [dict(item) for item in self.steps],
        }


class _CallFailure(AuthoringFailure):
    """Transport response failure with a private, short-lived body view."""


@dataclass(frozen=True, slots=True)
class _ResponseView:
    status_code: int
    data: object | None


def _safe_error_code(value: object, default: str = "http_error") -> str:
    if isinstance(value, Mapping):
        for key in ("code", "safe_error_code", "error_code"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate):
                return candidate
        detail = value.get("detail")
        if isinstance(detail, Mapping):
            return _safe_error_code(detail, default)
    return default


def _contains_acceptance_unknown(value: object, *, depth: int = 0) -> bool:
    """Read only reviewed status fields; never scan arbitrary response text."""

    if depth > 5:
        return False
    if isinstance(value, Mapping):
        for key in (
            "code",
            "safe_error_code",
            "error_code",
            "status",
            "state",
            "status_code",
        ):
            if value.get(key) == "acceptance_unknown":
                return True
        for key in (
            "detail",
            "provider",
            "publication",
            "operation",
            "result",
            "items",
            "data",
            "payload",
        ):
            if _contains_acceptance_unknown(value.get(key), depth=depth + 1):
                return True
    elif isinstance(value, list):
        return any(
            _contains_acceptance_unknown(item, depth=depth + 1) for item in value
        )
    return False


def _response_view(value: object) -> _ResponseView:
    if isinstance(value, _ResponseView):
        return value
    if isinstance(value, Mapping):
        # A fake may return a response envelope, while a small transport often
        # returns the JSON body directly.  Support both without retaining raw
        # HTTP objects.
        status = value.get("status_code")
        if isinstance(status, int) and not isinstance(status, bool) and "data" in value:
            return _ResponseView(status, value.get("data"))
        return _ResponseView(200, value)
    status = getattr(value, "status_code", None)
    data = getattr(value, "data", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return _ResponseView(status, data)
    raise AuthoringFailure("response_invalid")


def _exception_code(error: BaseException) -> str:
    for key in ("code", "safe_error_code", "error_code"):
        candidate = getattr(error, key, None)
        if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate):
            return candidate
    return "transport_unavailable"


def _exception_status(error: BaseException) -> int | None:
    value = getattr(error, "status_code", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _exception_data(error: BaseException) -> object | None:
    for key in ("data", "body", "response_data"):
        value = getattr(error, key, None)
        if value is not None:
            return value
    return None


def _call(
    transport: SessionTransport,
    method: str,
    path: str,
    *,
    payload: object | None = None,
    idempotency_key: str | None = None,
    csrf: bool = True,
    multipart: Mapping[str, object] | None = None,
) -> object:
    """Call one public route and reduce every failure to a safe code."""

    try:
        if multipart is None:
            response = transport.request(
                method,
                path,
                payload=payload,
                idempotency_key=idempotency_key,
                csrf=csrf,
            )
        else:
            method_fn = getattr(transport, "request_multipart", None)
            if not callable(method_fn):
                raise AuthoringFailure("multipart_transport_unavailable")
            response = method_fn(
                method,
                path,
                fields=cast(Mapping[str, str], multipart["fields"]),
                file_name=cast(str, multipart["file_name"]),
                file_content=cast(bytes, multipart["file_content"]),
                content_type=cast(str, multipart["content_type"]),
                idempotency_key=idempotency_key,
                csrf=csrf,
            )
    except AuthoringFailure:
        raise
    except Exception as error:  # noqa: BLE001 - transport errors become safe codes
        raise _CallFailure(
            _exception_code(error),
            status_code=_exception_status(error),
            data=_exception_data(error),
        ) from None

    view = _response_view(response)
    if _contains_acceptance_unknown(view.data):
        raise _CallFailure(
            "acceptance_unknown", status_code=view.status_code, data=view.data
        )
    if view.status_code < 200 or view.status_code >= 300:
        raise _CallFailure(
            _safe_error_code(view.data),
            status_code=view.status_code,
            data=view.data,
        )
    return view.data


def _mapping(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AuthoringFailure(code)
    return dict(cast(Mapping[str, object], value))


def _required_text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthoringFailure(code)
    return value


def _required_id(value: object, code: str) -> str:
    text = _required_text(value, code)
    if not _SAFE_ID.fullmatch(text):
        raise AuthoringFailure(code)
    return text


def _revision(value: object, code: str = "revision_invalid") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuthoringFailure(code)
    return value


def _required_sha(value: object, code: str = "hash_invalid") -> str:
    text = _required_text(value, code)
    if not _SHA256.fullmatch(text):
        raise AuthoringFailure(code)
    return text


def _required_raw_sha(value: object, code: str = "raw_hash_invalid") -> str:
    text = _required_text(value, code)
    if not _RAW_SHA256.fullmatch(text):
        raise AuthoringFailure(code)
    return text


def _spec_value(spec: object, field: str) -> object | None:
    if isinstance(spec, Mapping):
        return spec.get(field)
    return getattr(spec, field, None)


def _safe_fragment(value: str, fallback: str) -> str:
    fragment = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")
    return (fragment or fallback)[:28]


def _load_corpus(
    corpus: bytes | bytearray | memoryview | str | Path | None,
    corpus_bytes: bytes | bytearray | memoryview | None,
) -> bytes:
    if corpus is not None and corpus_bytes is not None:
        raise AuthoringFailure("corpus_source_ambiguous")
    source: object = corpus_bytes if corpus_bytes is not None else corpus
    if source is None:
        source = DEFAULT_CORRECT_CORPUS
    if isinstance(source, (bytes, bytearray, memoryview)):
        content = bytes(source)
    elif isinstance(source, (str, Path)):
        try:
            content = Path(source).read_bytes()
        except (OSError, ValueError):
            raise AuthoringFailure("corpus_unavailable") from None
    else:
        raise AuthoringFailure("corpus_invalid")
    if not content:
        raise AuthoringFailure("corpus_empty")
    return content


def _persona_markdown(name: str, slot: PersonaSlot) -> str:
    """Render only the current five-section grammar."""

    cultural = "\n".join(f"- {item}" for item in slot.cultural_lens)
    values = "\n".join(f"- {item}" for item in slot.core_values)
    return (
        f"# {name}\n\n"
        "## Identity\n\n"
        f"- Role: {slot.role}\n"
        f"- Historical or cultural context: {slot.historical_context}\n\n"
        "## Cultural lens\n\n"
        f"{cultural}\n\n"
        "## Core values\n\n"
        f"{values}\n\n"
        "## Initial position\n\n"
        f"{slot.initial_position}\n\n"
        "## Speaking style\n\n"
        f"- Tone: {slot.tone}\n"
        f"- Argument pattern: {slot.argument_pattern}\n"
        f"- Concession style: {slot.concession_style}\n"
        f"- Question style: {slot.question_style}\n"
    )


class _KeyFactory:
    def __init__(self, session_id: str, run_id: str | None) -> None:
        session = _safe_fragment(session_id, "session")
        run = _safe_fragment(run_id or "run", "run")
        self.prefix = f"nwa-{session}-{run}"

    def new(self, stage: str, slot: int) -> str:
        # A fresh key for every mutation prevents a failed/unknown operation
        # from being mistaken for a safe replay of a different stage.
        safe_stage = _safe_fragment(stage, "stage")
        return f"{self.prefix}-s{slot + 1}-{safe_stage}-{uuid4().hex}"


def _zero_provider_sends(
    failure: AuthoringFailure, transport: SessionTransport
) -> bool:
    """Accept the exact preflight error only when no send marker is nonzero.

    The public ``provider_confirmation_required`` route is raised before an
    external request.  Some test/adaptor transports additionally expose a
    safe count; if one is present, a nonzero value makes the flow fail closed.
    """

    containers: list[object] = [failure._response_data]
    details = getattr(failure, "details", None)
    if details is not None:
        containers.append(details)
    for key in (
        "provider_send_count",
        "charged_request_count",
        "provider_attempt_count",
        "provider_call_count",
        "provider_calls",
        "provider_request_count",
        "external_request_count",
    ):
        value = getattr(transport, key, None)
        if value is not None:
            containers.append({key: value})
    marker_names = {
        "provider_send_count",
        "provider_sends",
        "send_count",
        "sent_count",
        "sent_requests",
        "requests_sent",
        "charged_request_count",
        "charged_requests",
        "provider_attempt_count",
        "provider_attempts",
        "provider_call_count",
        "provider_calls",
        "provider_request_count",
        "external_request_count",
    }
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in marker_names:
            if key not in container:
                continue
            value = container[key]
            if isinstance(value, bool) or not isinstance(value, int) or value != 0:
                return False
    return True


class _Recorder:
    def __init__(self) -> None:
        self.steps: list[dict[str, object]] = []

    def success(self, stage: str, started: float, *, status: str = "passed") -> None:
        self.steps.append(
            {
                "stage": stage,
                "status": status,
                "wall_ms": max(0, int((time.monotonic() - started) * 1000)),
            }
        )

    def failure(
        self, stage: str, started: float, error: BaseException
    ) -> AuthoringFailure:
        if isinstance(error, AuthoringFailure):
            failure = error
        else:
            failure = AuthoringFailure("authoring_failed")
        self.steps.append(
            {
                "stage": stage,
                "status": "failed",
                "wall_ms": max(0, int((time.monotonic() - started) * 1000)),
                "error_code": failure.code,
            }
        )
        failure.stage = stage
        failure.steps = tuple(dict(item) for item in self.steps)
        return failure

    def run(self, stage: str, operation: Any) -> object:
        started = time.monotonic()
        try:
            value = operation()
        except Exception as error:  # noqa: BLE001 - stage failures are classified below
            failure = self.failure(stage, started, error)
            raise failure from None
        self.success(stage, started)
        return value


def _agent_and_initial_version(created: object) -> tuple[str, dict[str, object], int]:
    body = _mapping(created, "agent_create_response_invalid")
    agent = body
    nested_agent = body.get("agent")
    if isinstance(nested_agent, Mapping):
        agent = dict(cast(Mapping[str, object], nested_agent))
    agent_id = _required_id(agent.get("id"), "agent_id_invalid")
    versions = body.get("versions")
    if not isinstance(versions, list) or not versions:
        raise AuthoringFailure("agent_version_missing")
    version = _mapping(versions[0], "agent_version_invalid")
    version_id = _required_id(version.get("id"), "version_id_invalid")
    if version.get("state") != "draft":
        raise AuthoringFailure("agent_draft_invalid")
    version_agent_id = version.get("agent_id")
    if (
        version_agent_id is not None
        and _required_id(version_agent_id, "version_agent_invalid") != agent_id
    ):
        raise AuthoringFailure("agent_version_owner_mismatch")
    return agent_id, {**version, "id": version_id}, _revision(version.get("revision"))


def _version_response(
    value: object, expected_version_id: str, *, code: str
) -> tuple[dict[str, object], int]:
    body = _mapping(value, code)
    returned_id = _required_id(
        body.get("id") or body.get("version_id"), "version_id_invalid"
    )
    if returned_id != expected_version_id:
        raise AuthoringFailure("version_id_mismatch")
    state = body.get("state")
    if state is not None and state != "draft":
        raise AuthoringFailure("draft_state_invalid")
    return body, _revision(body.get("revision"))


def _published_response(
    value: object,
    expected_version_id: str,
    *,
    expected_agent_id: str | None = None,
) -> tuple[dict[str, object], str]:
    body = _mapping(value, "publish_response_invalid")
    returned_id = _required_id(body.get("id"), "version_id_invalid")
    if returned_id != expected_version_id:
        raise AuthoringFailure("version_id_mismatch")
    returned_agent = body.get("agent_id")
    if (
        expected_agent_id is not None
        and returned_agent is not None
        and _required_id(returned_agent, "agent_id_invalid") != expected_agent_id
    ):
        raise AuthoringFailure("agent_id_mismatch")
    if body.get("state") != "published":
        raise AuthoringFailure("publish_state_invalid")
    snapshot_id = _required_id(body.get("knowledge_snapshot_id"), "snapshot_id_invalid")
    return body, snapshot_id


def _pending_manifest(value: object, expected_version_id: str) -> tuple[str, int]:
    body = _mapping(value, "disclosure_pending_invalid")
    owner = body.get("agent_version_id")
    if (
        owner is not None
        and _required_id(owner, "disclosure_owner_invalid") != expected_version_id
    ):
        raise AuthoringFailure("disclosure_owner_mismatch")
    items = body.get("items")
    if not isinstance(items, list) or len(items) != 1:
        raise AuthoringFailure("disclosure_pending_invalid")
    item = _mapping(items[0], "disclosure_manifest_invalid")
    if item.get("confirmed") is not False:
        raise AuthoringFailure("disclosure_already_confirmed")
    manifest = _required_sha(item.get("manifest_hash"), "manifest_hash_invalid")
    revision = _revision(
        item.get("confirmation_revision"), "disclosure_revision_invalid"
    )
    if revision < 1:
        raise AuthoringFailure("disclosure_revision_invalid")
    return manifest, revision


def _disclosure(
    value: object, expected_manifest: str, expected_revision: int
) -> tuple[str, str, int]:
    body = _mapping(value, "disclosure_response_invalid")
    manifest = _required_sha(body.get("manifest_hash"), "manifest_hash_invalid")
    policy = _required_sha(body.get("policy_hash"), "policy_hash_invalid")
    revision = _revision(
        body.get("confirmation_revision"), "disclosure_revision_invalid"
    )
    if manifest != expected_manifest or revision != expected_revision:
        raise AuthoringFailure("disclosure_revision_mismatch")
    return manifest, policy, revision


def _confirmed_disclosure(
    value: object, manifest: str, policy: str, revision: int
) -> None:
    body = _mapping(value, "disclosure_confirm_response_invalid")
    if (
        _required_sha(body.get("manifest_hash"), "manifest_hash_invalid") != manifest
        or _required_sha(body.get("policy_hash"), "policy_hash_invalid") != policy
        or _revision(body.get("confirmation_revision"), "disclosure_revision_invalid")
        != revision
    ):
        raise AuthoringFailure("disclosure_confirmation_mismatch")


def _teacher_confirmation(
    recorder: _Recorder,
    teacher: SessionTransport,
    *,
    version_id: str,
    slot: int,
    keys: _KeyFactory,
) -> None:
    pending = cast(
        tuple[str, int],
        recorder.run(
            f"slot_{slot + 1}.provider_pending",
            lambda: _pending_manifest(
                _call(
                    teacher,
                    "GET",
                    f"/api/v1/provider/data-call/pending/agent-versions/{version_id}",
                    csrf=False,
                ),
                version_id,
            ),
        ),
    )
    manifest, pending_revision = pending
    disclosed = cast(
        tuple[str, str, int],
        recorder.run(
            f"slot_{slot + 1}.provider_disclosure",
            lambda: _disclosure(
                _call(
                    teacher,
                    "GET",
                    f"/api/v1/provider/data-call/disclosure?manifest_hash={manifest}",
                    csrf=False,
                ),
                manifest,
                pending_revision,
            ),
        ),
    )
    manifest, policy, revision = disclosed
    recorder.run(
        f"slot_{slot + 1}.provider_disclosure_confirm",
        lambda: _confirmed_disclosure(
            _call(
                teacher,
                "POST",
                "/api/v1/provider/data-call/disclosure/confirm",
                payload={
                    "policy_hash": policy,
                    "manifest_hash": manifest,
                    "expected_revision": revision,
                },
                idempotency_key=keys.new("provider-disclosure-confirm", slot),
            ),
            manifest,
            policy,
            revision,
        ),
    )


def author_session_agents(
    spec: object,
    transport: SessionTransport | None = None,
    *,
    student: SessionTransport | None = None,
    student_transport: SessionTransport | None = None,
    teacher: SessionTransport | None = None,
    teacher_transport: SessionTransport | None = None,
    group_id: str | None = None,
    corpus: bytes | bytearray | memoryview | str | Path | None = None,
    corpus_bytes: bytes | bytearray | memoryview | None = None,
    corpus_path: str | Path | None = None,
    session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    """Create and publish fresh synthetic Agents for one session spec.

    The operation is strictly sequential per slot.  A failure, including
    ``acceptance_unknown``, raises ``AuthoringFailure`` and no later stage or
    slot is attempted.  On success the result contains only public IDs and
    redacted timing/status rows.
    """

    if (
        student is not None
        and student_transport is not None
        and student is not student_transport
    ):
        raise AuthoringFailure("transport_ambiguous")
    if (
        teacher is not None
        and teacher_transport is not None
        and teacher is not teacher_transport
    ):
        raise AuthoringFailure("transport_ambiguous")
    if transport is not None and student is not None and transport is not student:
        raise AuthoringFailure("transport_ambiguous")
    resolved_student = (
        student
        if student is not None
        else student_transport
        if student_transport is not None
        else transport
    )
    resolved_teacher = teacher if teacher is not None else teacher_transport
    if resolved_student is None:
        raise AuthoringFailure("student_transport_required")

    raw_session = (
        session_id if session_id is not None else _spec_value(spec, "session_id")
    )
    resolved_session = _required_id(raw_session, "session_id_invalid")
    raw_count = _spec_value(spec, "agent_count")
    if (
        isinstance(raw_count, bool)
        or not isinstance(raw_count, int)
        or not 2 <= raw_count <= 5
    ):
        raise AuthoringFailure("agent_count_invalid")
    raw_group = group_id if group_id is not None else _spec_value(spec, "group_id")
    resolved_group = _required_id(raw_group, "group_id_invalid")
    if corpus_path is not None:
        if corpus is not None or corpus_bytes is not None:
            raise AuthoringFailure("corpus_source_ambiguous")
        corpus = corpus_path
    material = _load_corpus(corpus, corpus_bytes)
    keys = _KeyFactory(resolved_session, run_id)
    recorder = _Recorder()
    session_fragment = _safe_fragment(resolved_session, "session")

    agent_ids: list[str] = []
    version_ids: list[str] = []
    snapshot_ids: list[str] = []
    per_agent: list[dict[str, object]] = []
    names: set[str] = set()

    for slot_index in range(raw_count):
        persona_slot = PERSONA_SLOTS[slot_index]
        name = f"NW-{session_fragment}-{slot_index + 1}-{uuid4().hex[:8]}"
        if (
            name in names
        ):  # pragma: no cover - UUID collision is extraordinarily unlikely
            raise AuthoringFailure("agent_name_collision")
        names.add(name)
        markdown = _persona_markdown(name, persona_slot)

        created = recorder.run(
            f"slot_{slot_index + 1}.create",
            lambda name=name, slot=slot_index: _agent_and_initial_version(
                _call(
                    resolved_student,
                    "POST",
                    f"/api/v1/groups/{resolved_group}/agents",
                    payload={
                        "name": name,
                        "description": "Synthetic Next Wave acceptance Agent",
                    },
                    idempotency_key=keys.new("agent-create", slot),
                )
            ),
        )
        agent_id, version, revision = cast(tuple[str, dict[str, object], int], created)
        if agent_id in agent_ids or version["id"] in version_ids:
            raise AuthoringFailure("agent_identity_duplicate")
        version_id = cast(str, version["id"])

        written = recorder.run(
            f"slot_{slot_index + 1}.persona_write",
            lambda version_id=version_id, revision=revision, markdown=markdown, slot=slot_index: (
                _version_response(
                    _call(
                        resolved_student,
                        "PATCH",
                        f"/api/v1/agent-versions/{version_id}",
                        payload={"expected_revision": revision, "agent_md": markdown},
                        idempotency_key=keys.new("persona-write", slot),
                    ),
                    version_id,
                    code="persona_write_response_invalid",
                )
            ),
        )
        _, revision = cast(tuple[dict[str, object], int], written)

        uploaded = recorder.run(
            f"slot_{slot_index + 1}.knowledge_upload",
            lambda version_id=version_id, revision=revision, slot=slot_index: (
                _version_response(
                    _mapping(
                        _call(
                            resolved_student,
                            "POST",
                            f"/api/v1/groups/{resolved_group}/knowledge-documents",
                            multipart={
                                "fields": {
                                    "target_agent_version_id": version_id,
                                    "expected_revision": str(revision),
                                },
                                "file_name": f"{session_fragment}-slot-{slot + 1}-correct.md",
                                "file_content": material,
                                "content_type": "text/markdown",
                            },
                            idempotency_key=keys.new("knowledge-upload", slot),
                        ),
                        "knowledge_upload_response_invalid",
                    ).get("agent_version"),
                    version_id,
                    code="knowledge_version_invalid",
                )
            ),
        )
        _, revision = cast(tuple[dict[str, object], int], uploaded)


        publish_started = time.monotonic()
        try:
            first_publish = _published_response(
                _call(
                    resolved_student,
                    "POST",
                    f"/api/v1/agent-versions/{version_id}/publish",
                    payload={"expected_revision": revision},
                    idempotency_key=keys.new("publish", slot_index),
                ),
                version_id,
                expected_agent_id=agent_id,
            )
        except AuthoringFailure as error:
            if (
                error.code != "provider_confirmation_required"
                or not _zero_provider_sends(error, resolved_student)
            ):
                failure = recorder.failure(
                    f"slot_{slot_index + 1}.publish", publish_started, error
                )
                raise failure from None
            recorder.success(
                f"slot_{slot_index + 1}.publish",
                publish_started,
                status="provider_confirmation_required",
            )
            if resolved_teacher is None:
                failure = AuthoringFailure("teacher_transport_required")
                failure = recorder.failure(
                    f"slot_{slot_index + 1}.provider_pending", time.monotonic(), failure
                )
                raise failure from None
            _teacher_confirmation(
                recorder,
                resolved_teacher,
                version_id=version_id,
                slot=slot_index,
                keys=keys,
            )
            republished = recorder.run(
                f"slot_{slot_index + 1}.publish_after_confirmation",
                lambda version_id=version_id, revision=revision, agent_id=agent_id, slot=slot_index: (
                    _published_response(
                        _call(
                            resolved_student,
                            "POST",
                            f"/api/v1/agent-versions/{version_id}/publish",
                            payload={"expected_revision": revision},
                            idempotency_key=keys.new("publish-confirmed", slot),
                        ),
                        version_id,
                        expected_agent_id=agent_id,
                    )
                ),
            )
            _published_body, snapshot_id = cast(
                tuple[dict[str, object], str], republished
            )
        else:
            recorder.success(f"slot_{slot_index + 1}.publish", publish_started)
            _published_body, snapshot_id = first_publish

        agent_ids.append(agent_id)
        version_ids.append(version_id)
        snapshot_ids.append(snapshot_id)
        per_agent.append(
            {
                "slot": slot_index + 1,
                "agent_id": agent_id,
                "version_id": version_id,
                "snapshot_id": snapshot_id,
                "state": "published",
            }
        )

    return {
        "schema_version": AUTHORING_SCHEMA_VERSION,
        "status": "published",
        "session_id": resolved_session,
        "agent_ids": agent_ids,
        "version_ids": version_ids,
        "snapshot_ids": snapshot_ids,
        "agents": per_agent,
        "steps": [dict(item) for item in recorder.steps],
    }


__all__ = [
    "AUTHORING_SCHEMA_VERSION",
    "DEFAULT_CORRECT_CORPUS",
    "PERSONA_COMPILER_VERSION",
    "PERSONA_SLOTS",
    "AuthoringFailure",
    "PersonaSlot",
    "SessionTransport",
    "author_session_agents",
]
