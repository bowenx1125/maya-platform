"""The immutable M07 avatar catalog and pure configuration validation.

The product exposes one compatible local head asset through three deliberate
parameter presets.  Keeping the catalog here gives draft validation, publish
blocker checks and the browser editor one source of truth without adding
provider or asset details to the frozen public ``AvatarConfig`` shape.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from pydantic import ValidationError

from app.modules.agents.schemas import AvatarConfig
from app.modules.avatars.schemas import AvatarTemplate

AVATAR_TEMPLATE_IDS: Final[tuple[str, ...]] = (
    "wave1-default-head",
    "maya-warm-scholar",
    "maya-civic-observer",
)
MATERIAL_THEMES: Final[tuple[str, ...]] = (
    "demo",
    "warm_sand",
    "cool_slate",
    "civic_olive",
)
EYE_COLORS: Final[tuple[str | None, ...]] = (
    None,
    "brown",
    "hazel",
    "blue",
    "green",
    "gray",
)
EXPRESSION_VALUES: Final[tuple[str, ...]] = (
    "neutral",
    "attentive",
    "happy",
    "serious_angry",
    "sad",
)
EXPRESSION_STRENGTHS: Final[tuple[str, ...]] = ("low", "medium", "high")
MOTION_STYLES: Final[tuple[str, ...]] = ("calm", "active")
CONFIG_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "template_id",
        "material_theme",
        "eye_color",
        "default_expression",
        "expression_strength",
        "motion_style",
    }
)

# This is intentionally a parameter capability list rather than a promise of
# separate meshes.  It is copied into each response so callers cannot mutate
# the server-owned tuple.
SUPPORTED_PARAMETERS: Final[tuple[str, ...]] = (
    "template_id",
    "material_theme",
    "eye_color",
    "default_expression",
    "expression_strength",
    "motion_style",
)


@dataclass(frozen=True)
class _CatalogEntry:
    id: str
    name: str
    available: bool
    defaults: AvatarConfig


def _config(
    template_id: str,
    material_theme: str,
    eye_color: str | None,
    default_expression: str,
    expression_strength: str,
    motion_style: str,
) -> AvatarConfig:
    return AvatarConfig(
        template_id=template_id,
        material_theme=material_theme,
        eye_color=eye_color,
        default_expression=default_expression,  # type: ignore[arg-type]
        expression_strength=expression_strength,  # type: ignore[arg-type]
        motion_style=motion_style,  # type: ignore[arg-type]
    )


_CATALOG: Final[tuple[_CatalogEntry, ...]] = (
    _CatalogEntry(
        id="wave1-default-head",
        name="Wave 1 Default Head",
        available=True,
        defaults=_config("wave1-default-head", "demo", None, "neutral", "medium", "calm"),
    ),
    _CatalogEntry(
        id="maya-warm-scholar",
        name="Maya Warm Scholar",
        available=True,
        defaults=_config("maya-warm-scholar", "warm_sand", "brown", "attentive", "medium", "calm"),
    ),
    _CatalogEntry(
        id="maya-civic-observer",
        name="Maya Civic Observer",
        available=True,
        defaults=_config(
            "maya-civic-observer",
            "civic_olive",
            "gray",
            "serious_angry",
            "medium",
            "active",
        ),
    ),
)
_BY_ID: Final[dict[str, _CatalogEntry]] = {entry.id: entry for entry in _CATALOG}

DEFAULT_AVATAR_CONFIG: Final[AvatarConfig] = _CATALOG[0].defaults
DISTINCT_COMPATIBLE_ASSET_COUNT: Final[int] = 1


class AvatarConfigValidationError(ValueError):
    """A draft avatar config is outside the frozen M07 catalog."""

    def __init__(self, message: str, *, field: str = "avatar_config") -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = "avatar_missing"
        self.details = {"field": field}


def avatar_templates() -> list[AvatarTemplate]:
    """Return a fresh, stable-order public catalog projection."""

    return [
        AvatarTemplate(
            id=entry.id,
            name=entry.name,
            available=entry.available,
            supported_parameters=list(SUPPORTED_PARAMETERS),
        )
        for entry in _CATALOG
    ]


def is_supported_template(template_id: str) -> bool:
    """Return whether ``template_id`` is an available catalog entry."""

    entry = _BY_ID.get(template_id)
    return entry is not None and entry.available


def compatible_asset_count() -> int:
    """Return the honest count of distinct compatible meshes in this demo."""

    return DISTINCT_COMPATIBLE_ASSET_COUNT


def _coerce_config(value: AvatarConfig | Mapping[str, object]) -> AvatarConfig:
    if isinstance(value, AvatarConfig):
        return value
    try:
        return AvatarConfig.model_validate(value)
    except ValidationError as exc:
        errors: list[Any] = exc.errors()
        first_error: Any = errors[0] if errors else None
        location = first_error.get("loc", ()) if isinstance(first_error, dict) else ()
        field = location[0] if location and isinstance(location[0], str) else "avatar_config"
        raise AvatarConfigValidationError(
            "The avatar configuration does not match the supported parameters.",
            field=field,
        ) from exc


def validate_avatar_config(value: AvatarConfig | Mapping[str, object]) -> AvatarConfig:
    """Validate and return an immutable-contract-compatible avatar config.

    This function has no database/filesystem/provider dependencies, making it
    safe to call from both draft updates and publish blocker computation.  It
    raises :class:`AvatarConfigValidationError` so HTTP adapters can map the
    existing ``avatar_missing`` business envelope without leaking Pydantic
    internals.
    """

    if isinstance(value, Mapping):
        unknown = sorted(set(value) - CONFIG_FIELDS)
        if unknown:
            raise AvatarConfigValidationError(
                "The avatar configuration contains an unsupported parameter.",
                field=unknown[0],
            )
    config = _coerce_config(value)
    entry = _BY_ID.get(config.template_id)
    if entry is None or not entry.available:
        raise AvatarConfigValidationError(
            "Choose an available avatar template before saving this draft.",
            field="template_id",
        )
    if config.material_theme not in MATERIAL_THEMES:
        raise AvatarConfigValidationError(
            "Choose a supported avatar material theme.",
            field="material_theme",
        )
    if config.eye_color not in EYE_COLORS:
        raise AvatarConfigValidationError(
            "Choose a supported avatar eye color.",
            field="eye_color",
        )
    # AvatarConfig already freezes these three fields at the schema layer, but
    # keep explicit checks here so this function remains the catalog boundary
    # if those DTO literals are widened for a future contract.
    if config.default_expression not in EXPRESSION_VALUES:
        raise AvatarConfigValidationError(
            "Choose a supported default expression.",
            field="default_expression",
        )
    if config.expression_strength not in EXPRESSION_STRENGTHS:
        raise AvatarConfigValidationError(
            "Choose a supported expression strength.",
            field="expression_strength",
        )
    if config.motion_style not in MOTION_STYLES:
        raise AvatarConfigValidationError(
            "Choose a supported motion style.",
            field="motion_style",
        )
    return config


def default_config_for(template_id: str) -> AvatarConfig:
    """Return a copy of one preset's defaults for a new editor."""

    entry = _BY_ID.get(template_id)
    if entry is None or not entry.available:
        raise AvatarConfigValidationError(
            "Choose an available avatar template before creating a draft.",
            field="template_id",
        )
    return AvatarConfig.model_validate(entry.defaults.model_dump())


def avatar_catalog_entries() -> tuple[AvatarTemplate, ...]:
    """Expose an immutable tuple for deterministic diagnostics and tests."""

    return tuple(avatar_templates())
