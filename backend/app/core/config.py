"""Runtime configuration.

The application deliberately keeps secret-bearing settings on the server.  A
missing or short session secret is accepted only for an explicitly test-mode
process; a normal server fails during startup instead of silently using a
guessable key.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings used by the Wave 0 backend."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Names intentionally match the repository .env.example and the frozen
    # provider/security contract.
    node_env: str = Field(default="development", validation_alias="NODE_ENV")
    demo_mode: bool = Field(default=False, validation_alias="DEMO_MODE")
    session_secret: str | None = Field(default=None, validation_alias="SESSION_SECRET")
    classroom_public_base_url: str | None = Field(
        default=None,
        validation_alias="CLASSROOM_PUBLIC_BASE_URL",
    )
    dashscope_api_key: str | None = Field(default=None, validation_alias="DASHSCOPE_API_KEY")
    dashscope_workspace_id: str | None = Field(
        default=None,
        validation_alias="DASHSCOPE_WORKSPACE_ID",
    )
    dashscope_region: str | None = Field(default=None, validation_alias="DASHSCOPE_REGION")
    deepl_api_key: str | None = Field(default=None, validation_alias="DEEPL_API_KEY")
    # Provider selectors intentionally default to local mocks.  They are
    # server-only switches; no provider identity is returned in API DTOs.
    llm_provider: str = Field(default="mock", validation_alias="LLM_PROVIDER")
    embedding_provider: str = Field(default="mock", validation_alias="EMBEDDING_PROVIDER")
    tts_provider: str = Field(default="mock", validation_alias="TTS_PROVIDER")
    voice_provider: str = Field(default="mock", validation_alias="VOICE_PROVIDER")
    translation_provider: str | None = Field(
        default=None,
        validation_alias="TRANSLATION_PROVIDER",
    )
    fallback_voice_profile_id: str | None = Field(
        default=None,
        validation_alias="FALLBACK_VOICE_PROFILE_ID",
    )

    # These server-only operational values are also part of C02/C08. They are
    # intentionally not exposed in browser-facing DTOs. ``DATABASE_URL`` is
    # useful for isolated tests and deployment-level Alembic smoke tests.
    database_url: str = Field(
        default="sqlite:///data/maya.sqlite3",
        validation_alias="DATABASE_URL",
    )
    data_root: Path = Field(default=Path("data"), validation_alias="DATA_ROOT")
    demo_users_file: Path = Field(
        default=Path("config/demo_users.yaml"),
        validation_alias="DEMO_USERS_FILE",
    )
    maya_env: str = Field(default="", validation_alias="MAYA_ENV")

    @field_validator("session_secret", mode="before")
    @classmethod
    def empty_secret_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("demo_mode", mode="before")
    @classmethod
    def empty_demo_mode_is_false(cls, value: object) -> object:
        # docker-compose forwards an empty value when DEMO_MODE is not set.
        # Treat that as the secure disabled default instead of a settings
        # parse failure.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "llm_provider",
        "embedding_provider",
        "tts_provider",
        "voice_provider",
        mode="before",
    )
    @classmethod
    def empty_provider_is_mock(cls, value: object) -> object:
        return "mock" if isinstance(value, str) and not value.strip() else value

    @property
    def is_test(self) -> bool:
        """Whether ephemeral test-only defaults may be used."""

        explicit = self.maya_env.strip().lower()
        if explicit in {"test", "testing"}:
            return True
        # pytest sets this variable while running a test. It makes a directly
        # constructed TestClient safe without changing a developer's shell.
        return bool(os.environ.get("PYTEST_CURRENT_TEST")) or os.environ.get("MAYA_TESTING") == "1"

    def validate_runtime(self) -> None:
        """Reject insecure production configuration at application startup."""

        if self.session_secret is None or len(self.session_secret.encode("utf-8")) < 32:
            if not self.is_test:
                raise RuntimeError("SESSION_SECRET must contain at least 32 bytes")

    @property
    def secret_bytes(self) -> bytes:
        """Return the signing key, using an ephemeral test key only in tests."""

        if self.session_secret is not None and len(self.session_secret.encode("utf-8")) >= 32:
            return self.session_secret.encode("utf-8")
        if self.is_test:
            return b"maya-wave0-test-session-secret-not-for-production"
        # Keep a clear failure even if a caller uses the property before the
        # lifespan validator.
        raise RuntimeError("SESSION_SECRET must contain at least 32 bytes")

    @property
    def resolved_data_root(self) -> Path:
        path = self.data_root
        if not path.is_absolute():
            # Resolve against the backend package directory when launched from
            # another working directory (for example by a process manager).
            path = Path(__file__).resolve().parents[2] / path
        return path

    @property
    def resolved_demo_users_file(self) -> Path:
        path = self.demo_users_file
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    def ensure_data_root(self) -> None:
        root = self.resolved_data_root
        root.mkdir(parents=True, exist_ok=True)
        # The Demo data root is private application state.  Apply the mode on
        # every startup so a copied directory cannot silently retain broad
        # permissions from a previous run.
        root.chmod(0o700)
        for relative in ("groups", "snapshots", "tmp", "tmp/publish", "private"):
            child = root / relative
            child.mkdir(parents=True, exist_ok=True)
            child.chmod(0o700)

    def cookie_secure(self, request_scheme: str | None = None) -> bool:
        """Use Secure cookies only when the active origin is HTTPS.

        The local Demo is intentionally served over HTTP by Caddy, so using a
        blanket production flag would make the browser drop the session.  A
        configured HTTPS classroom URL or an HTTPS request opts in securely.
        """

        if request_scheme and request_scheme.lower() == "https":
            return True
        if self.classroom_public_base_url:
            return urlsplit(self.classroom_public_base_url).scheme.lower() == "https"
        return False

    def ephemeral_test_secret(self) -> str:
        """Create a one-off secret for callers constructing test settings.

        This helper is intentionally explicit and never called for a normal
        process.  It is useful to tests that want independent app instances.
        """

        if not self.is_test:
            raise RuntimeError("ephemeral secrets are available only in test mode")
        return secrets.token_urlsafe(32)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Test/support hook for environment-isolated app instances."""

    get_settings.cache_clear()
