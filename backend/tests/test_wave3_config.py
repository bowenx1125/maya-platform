"""Wave 3 classroom-origin configuration safety checks."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("http://192.168.1.20:8080", "http://192.168.1.20:8080"),
        ("https://10.2.3.4/", "https://10.2.3.4"),
        ("http://172.20.1.4", "http://172.20.1.4"),
        ("http://maya.local:8080", "http://maya.local:8080"),
        ("http://[fd00::12]:8080", "http://[fd00::12]:8080"),
        ("http://localhost:8080", None),
        ("http://127.0.0.1:8080", None),
        ("http://0.0.0.0:8080", None),
        ("http://169.254.2.4:8080", None),
        ("https://8.8.8.8", None),
        ("https://classroom.example", None),
    ],
)
def test_classroom_public_origin_is_phone_reachable_private_lan_only(
    origin: str,
    expected: str | None,
) -> None:
    settings = Settings(maya_env="test", classroom_public_base_url=origin)

    assert settings.classroom_public_origin == expected


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://192.168.1.20",
        "http://user:password@192.168.1.20",
        "http://192.168.1.20/classroom",
        "http://192.168.1.20?token=secret",
        "http://192.168.1.20#fragment",
        "//192.168.1.20",
    ],
)
def test_classroom_public_base_url_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(maya_env="test", classroom_public_base_url=origin)
