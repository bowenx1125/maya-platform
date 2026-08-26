"""Demo credential file loading and Argon2 verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pwdlib import PasswordHash

from app.core.config import Settings


@dataclass(frozen=True)
class DemoCredential:
    user_id: str
    username: str
    password_hash: str


class CredentialFileError(RuntimeError):
    """Raised for a missing or malformed runtime credential file."""


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("users")
    else:
        value = payload
    if not isinstance(value, list):
        raise CredentialFileError("demo credential file must contain a users list")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            raise CredentialFileError("demo credential entries must be mappings")
        rows.append(row)
    return rows


def load_credentials(settings: Settings) -> tuple[DemoCredential, ...]:
    path: Path = settings.resolved_demo_users_file
    if not path.exists():
        raise CredentialFileError("demo credentials are not configured")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CredentialFileError("demo credentials could not be read") from exc
    credentials: list[DemoCredential] = []
    for row in _rows(payload):
        user_id = row.get("user_id")
        username = row.get("username")
        password_hash = row.get("password_hash")
        if (
            not isinstance(user_id, str)
            or not isinstance(username, str)
            or not isinstance(password_hash, str)
        ):
            raise CredentialFileError("demo credential entry is incomplete")
        try:
            parsed = str(UUID(user_id))
        except ValueError as exc:
            raise CredentialFileError("demo credential user_id is invalid") from exc
        if password_hash.startswith("REPLACE_"):
            # An example copied into runtime must not accidentally authenticate.
            continue
        credentials.append(DemoCredential(parsed, username, password_hash))
    return tuple(credentials)


def verify_password(settings: Settings, username: str, password: str) -> str | None:
    """Return the configured user ID for a valid password, else ``None``."""

    try:
        credentials = load_credentials(settings)
    except CredentialFileError:
        return None
    hasher = PasswordHash.recommended()
    for credential in credentials:
        if credential.username != username:
            continue
        try:
            if hasher.verify(password, credential.password_hash):
                return credential.user_id
        except (ValueError, TypeError):
            return None
    return None
