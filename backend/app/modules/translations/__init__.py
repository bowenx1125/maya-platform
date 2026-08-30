"""M15 history-derived, on-demand translation boundary.

The translation package is deliberately downstream-only.  It can enrich a
teacher history read model with an exact, ready translation, but it is never
imported by debate generation, retrieval, playback or report input builders.
"""

from .manifest import (
    TranslationInputManifestV1,
    build_translation_manifest,
    canonical_json_bytes,
    manifest_hash,
    source_text_hash,
)
from .policy import (
    MOCK_TRANSLATION_POLICY,
    MOCK_TRANSLATION_QUALITY,
    MockTranslationProvider,
    TranslationProvider,
)
from .router import router
from .service import (
    TranslationEventPayload,
    TranslationService,
    TranslationTaskManager,
    attach_translated_report,
    attach_translated_text,
    startup_translation_service,
)

__all__ = [
    "MOCK_TRANSLATION_POLICY",
    "MOCK_TRANSLATION_QUALITY",
    "MockTranslationProvider",
    "TranslationInputManifestV1",
    "TranslationProvider",
    "TranslationEventPayload",
    "TranslationService",
    "TranslationTaskManager",
    "attach_translated_report",
    "attach_translated_text",
    "build_translation_manifest",
    "canonical_json_bytes",
    "manifest_hash",
    "router",
    "source_text_hash",
    "startup_translation_service",
]
