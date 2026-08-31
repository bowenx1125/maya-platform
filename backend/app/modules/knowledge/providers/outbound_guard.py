"""Fail-closed scan for real Embedding outbound text.

The provider-control manifest already rejects forbidden *structured* fields.
Embedding inputs are plain text, so they need a small independent boundary
before their text hashes or provider manifests are persisted.  This module is
deliberately provider-neutral: it does not inspect Persona data, select a
resource, or perform I/O.  Callers pass only the document chunks or turn
queries that are actually eligible for real Embedding.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


class OutboundEmbeddingDataError(ValueError):
    """A real Embedding input contains a forbidden secret or private identity."""

    code = "embedding_outbound_data_forbidden"

    def __init__(self, message: str = "real embedding input contains forbidden data") -> None:
        # Never include the offending text or a match in the exception.  The
        # message is safe for a product-level error wrapper and test logs.
        super().__init__(message)


EmbeddingOutboundGuardError = OutboundEmbeddingDataError


# Labels are intentionally bounded and data-shaped.  This rejects an
# accidental field dump (``api_key=...``/``student_id: ...``) without treating
# ordinary words such as "secretary" or a general discussion of credentials as
# a private record.
_PRIVATE_IDENTITY_LABEL_RE = re.compile(
    r"(?ix)\b(?:student|user|participant|teacher|member|personal|private)[\s_-]+"
    r"(?:id|identifier|name|email|phone|telephone|mobile|nickname|username|"
    r"identity|account)\b\s*[\"']?\s*(?:[:=]|\bis\b)"
)
_PRIVATE_IDENTITY_ASSIGNMENT_RE = re.compile(
    r"(?ix)(?:^|[\r\n\t{[(,\"'])\s*(?:id|identifier|name|email|phone|"
    r"telephone|mobile|nickname|username|identity|account)[\s_-]*"
    r"(?:value|number)?\s*[\"']?\s*(?:[:=]|\bis\b)"
)
_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?ix)\b(?:api[\s_-]*key|authorization|bearer|credential(?:s)?|"
    r"password|secret)\b\s*[\"']?\s*(?:[:=]|is)"
)
_SENSITIVE_FIELD_LINE_RE = re.compile(
    r"(?im)^\s*(?:api[\s_-]*key|authorization|bearer|credential(?:s)?|"
    r"password|secret)\s*(?:[:=]|$)"
)
_PRIVATE_IDENTITY_PHRASE_RE = re.compile(
    r"(?ix)\b(?:private|personal|real)[\s_-]+identity\b\s*[\"']?\s*(?:[:=]|\bis\b)"
)
_UUID_RE = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[\s-]?)?1[3-9]\d{9}(?!\d)")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{7,}\b")
_PRIVATE_NUMBER_RE = re.compile(
    r"(?ix)\b(?:student|user|participant|member|account)[\s_-]+"
    r"(?:id|identifier|number)\s*[:=#-]?\s*[0-9][0-9 -]{4,}[0-9]\b"
)
_CJK_PRIVATE_IDENTITY_RE = re.compile(
    r"(?:学生|用户|参与者|教师|成员)(?:编号|号码|姓名|名字|邮箱|电话|账号|身份)\s*[：:]"
)


def scan_real_embedding_text(value: str, *, field_name: str = "embedding input") -> None:
    """Reject one text value that could carry a secret/private identity.

    The scanner intentionally does not perform general PII/name recognition.
    A normal lesson mentioning governance, privacy, identity as a concept, or
    account security remains valid; only explicit credential/identity-shaped
    labels and machine-shaped private identifiers are blocked.
    """

    if not isinstance(value, str):
        raise OutboundEmbeddingDataError(f"{field_name} is not text")
    if (
        _PRIVATE_IDENTITY_LABEL_RE.search(value)
        or _PRIVATE_IDENTITY_ASSIGNMENT_RE.search(value)
        or _CREDENTIAL_ASSIGNMENT_RE.search(value)
        or _SENSITIVE_FIELD_LINE_RE.search(value)
        or _PRIVATE_IDENTITY_PHRASE_RE.search(value)
        or _UUID_RE.search(value)
        or _EMAIL_RE.search(value)
        or _PHONE_RE.search(value)
        or _BEARER_TOKEN_RE.search(value)
        or _SECRET_TOKEN_RE.search(value)
        or _PRIVATE_NUMBER_RE.search(value)
        or _CJK_PRIVATE_IDENTITY_RE.search(value)
    ):
        raise OutboundEmbeddingDataError(f"{field_name} contains forbidden data")


def scan_real_embedding_texts(
    values: Iterable[str],
    *,
    field_name: str = "embedding input",
) -> None:
    """Scan an iterable of eligible real Embedding text values exactly once."""

    for index, value in enumerate(values):
        scan_real_embedding_text(value, field_name=f"{field_name}[{index}]")


# Descriptive aliases keep the small boundary easy to discover from the
# publication/query modules without duplicating matching semantics.
validate_real_embedding_text = scan_real_embedding_text
validate_real_embedding_texts = scan_real_embedding_texts


__all__ = [
    "EmbeddingOutboundGuardError",
    "OutboundEmbeddingDataError",
    "scan_real_embedding_text",
    "scan_real_embedding_texts",
    "validate_real_embedding_text",
    "validate_real_embedding_texts",
]
