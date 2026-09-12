"""Canonical identity keys shared by persistence and account workflows."""

import unicodedata

GROUP_NAME_MAX = 200


def username_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_group_name(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized:
        raise ValueError("A group name is required.")
    if len(normalized) > GROUP_NAME_MAX:
        raise ValueError(f"A group name may not exceed {GROUP_NAME_MAX} characters.")
    if any(ord(character) < 0x20 for character in normalized):
        raise ValueError("A group name may not contain control characters.")
    return normalized


def group_name_key(value: str) -> str:
    return normalize_group_name(value).casefold()
