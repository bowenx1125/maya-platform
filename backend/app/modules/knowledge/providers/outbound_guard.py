"""Shape check for real Embedding outbound text."""

from __future__ import annotations

from collections.abc import Iterable


class OutboundEmbeddingDataError(ValueError):
    """A real Embedding input contains a forbidden secret or private identity."""

    code = "embedding_outbound_data_forbidden"

    def __init__(self, message: str = "real embedding input contains forbidden data") -> None:
        # Never include the offending text or a match in the exception.  The
        # message is safe for a product-level error wrapper and test logs.
        super().__init__(message)


EmbeddingOutboundGuardError = OutboundEmbeddingDataError


def scan_real_embedding_text(value: str, *, field_name: str = "embedding input") -> None:
    """Require a text value without applying content-based rejection rules."""

    if not isinstance(value, str):
        raise OutboundEmbeddingDataError(f"{field_name} is not text")


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
