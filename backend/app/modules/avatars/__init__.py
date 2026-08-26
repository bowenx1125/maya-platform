"""Avatar catalog and renderer-facing contracts."""

from .catalog import (
    AVATAR_TEMPLATE_IDS,
    DEFAULT_AVATAR_CONFIG,
    EYE_COLORS,
    MATERIAL_THEMES,
    AvatarConfigValidationError,
    avatar_templates,
    compatible_asset_count,
    default_config_for,
    is_supported_template,
    validate_avatar_config,
)
from .schemas import AvatarTemplate

__all__ = [
    "AVATAR_TEMPLATE_IDS",
    "AvatarConfigValidationError",
    "DEFAULT_AVATAR_CONFIG",
    "EYE_COLORS",
    "MATERIAL_THEMES",
    "AvatarTemplate",
    "compatible_asset_count",
    "default_config_for",
    "avatar_templates",
    "is_supported_template",
    "validate_avatar_config",
]
