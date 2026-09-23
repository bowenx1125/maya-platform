"""Runtime configuration.

The application deliberately keeps secret-bearing settings on the server.  A
missing or short session secret is accepted only for an explicitly test-mode
process; a normal server fails during startup instead of silently using a
guessable key.
"""

from __future__ import annotations

import os
import re
import secrets
from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dated snapshot, not the floating qwen3.8-max alias. LLM_MODEL overrides it.
DEFAULT_LLM_MODEL = "qwen3.8-max-2026-09-02"
_LLM_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


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
    # Passwordless identity selection is intentionally a separate explicit
    # Demo-only capability: either flag being off must hide the route.
    demo_quick_login: bool = Field(default=False, validation_alias="DEMO_QUICK_LOGIN")
    # Standing consent for the provider data-call disclosure, recorded here
    # rather than implied by DEMO_MODE so the decision is visible in .env and
    # has to be taken deliberately. It only has effect while DEMO_MODE is on.
    # With it off, a person confirms each disclosure exactly as before.
    demo_auto_confirm_provider: bool = Field(
        default=False, validation_alias="DEMO_AUTO_CONFIRM_PROVIDER"
    )
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
    provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="PROVIDER_POLICY_HASH",
    )
    # Real-Core Demo uses endpoint-bound policy hashes per Provider slice.  The
    # legacy single hash remains accepted only when exactly one real slice is
    # selected; dual Real Embedding + Real LLM must provide both values.
    embedding_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="EMBEDDING_PROVIDER_POLICY_HASH",
    )
    llm_model: str = Field(default=DEFAULT_LLM_MODEL, validation_alias="LLM_MODEL")
    llm_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="LLM_PROVIDER_POLICY_HASH",
    )
    report_provider_policy_hash: str | None = Field(
        default=None,
        validation_alias="REPORT_PROVIDER_POLICY_HASH",
    )
    deepl_api_key: str | None = Field(default=None, validation_alias="DEEPL_API_KEY")
    # Provider selectors intentionally default to local mocks.  They are
    # server-only switches; no provider identity is returned in API DTOs.
    llm_provider: str = Field(default="mock", validation_alias="LLM_PROVIDER")
    report_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices("MAYA_REPORT_PROVIDER", "report_provider"),
    )
    embedding_provider: str = Field(default="mock", validation_alias="EMBEDDING_PROVIDER")
    tts_provider: str = Field(default="mock", validation_alias="TTS_PROVIDER")
    voice_provider: str = Field(default="mock", validation_alias="VOICE_PROVIDER")
    fallback_voice_profile_id: str | None = Field(
        default=None,
        validation_alias="FALLBACK_VOICE_PROFILE_ID",
    )
    # Debates (beta) shows a join code on the stage and flies classroom
    # messages across it while the Agents are still speaking, which the
    # after-the-debate gate forbids.  Off by default: with the switch off the
    # classic Debates surface behaves exactly as it always has.
    debates_beta_live_interaction: bool = Field(
        default=False,
        validation_alias="DEBATES_BETA_LIVE_INTERACTION",
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
    demo_accounts_file: Path = Field(
        default=Path("config/demo-accounts/accounts.private.md"),
        validation_alias="DEMO_ACCOUNTS_FILE",
    )
    # Explicit one-time compatibility switch for a legacy YAML migration. It
    # defaults off so an old YAML file cannot silently become a second runtime
    # credential source after the private Markdown catalog is adopted.
    allow_legacy_demo_users: bool = Field(
        default=False,
        validation_alias="ALLOW_LEGACY_DEMO_USERS",
    )
    maya_env: str = Field(default="", validation_alias="MAYA_ENV")

    @field_validator("session_secret", mode="before")
    @classmethod
    def empty_secret_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("classroom_public_base_url", mode="before")
    @classmethod
    def classroom_public_url_is_origin(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("CLASSROOM_PUBLIC_BASE_URL must be an HTTP origin")
        parsed = urlsplit(value.strip())
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("CLASSROOM_PUBLIC_BASE_URL has an invalid port") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "CLASSROOM_PUBLIC_BASE_URL must be an absolute HTTP origin without a path"
            )
        return f"{parsed.scheme}://{parsed.netloc}"

    @field_validator("demo_mode", mode="before")
    @classmethod
    def empty_demo_mode_is_false(cls, value: object) -> object:
        # docker-compose forwards an empty value when DEMO_MODE is not set.
        # Treat that as the secure disabled default instead of a settings
        # parse failure.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator("demo_quick_login", mode="before")
    @classmethod
    def empty_demo_quick_login_is_false(cls, value: object) -> object:
        # Compose forwards an empty value when DEMO_QUICK_LOGIN is unset.
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator("allow_legacy_demo_users", mode="before")
    @classmethod
    def empty_legacy_demo_users_is_false(cls, value: object) -> object:
        return False if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "llm_provider",
        "report_provider",
        "embedding_provider",
        "tts_provider",
        "voice_provider",
        mode="before",
    )
    @classmethod
    def empty_provider_is_mock(cls, value: object) -> object:
        return "mock" if isinstance(value, str) and not value.strip() else value

    @field_validator(
        "llm_provider",
        "report_provider",
        "embedding_provider",
        "tts_provider",
        "voice_provider",
    )
    @classmethod
    def provider_selector_is_supported(cls, value: str) -> str:
        if value not in {"mock", "dashscope"}:
            raise ValueError("provider selector must be mock or dashscope")
        return value

    @field_validator("fallback_voice_profile_id")
    @classmethod
    def fallback_id_is_uuid(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            UUID(value)
        except ValueError:
            raise ValueError("FALLBACK_VOICE_PROFILE_ID must be a UUID") from None
        return value

    @field_validator("provider_policy_hash", mode="before")
    @classmethod
    def provider_policy_hash_is_explicit_sha256(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value.strip()) is None:
            raise ValueError("PROVIDER_POLICY_HASH must be a lowercase SHA-256 value")
        return value.strip()

    @field_validator("llm_model", mode="before")
    @classmethod
    def llm_model_is_an_explicit_id(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_LLM_MODEL
        if not isinstance(value, str) or _LLM_MODEL_RE.fullmatch(value.strip()) is None:
            raise ValueError("LLM_MODEL must be a model id")
        return value.strip()

    @field_validator(
        "embedding_provider_policy_hash",
        "llm_provider_policy_hash",
        "report_provider_policy_hash",
        mode="before",
    )
    @classmethod
    def provider_slice_policy_hash_is_explicit_sha256(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value.strip()) is None:
            raise ValueError("provider slice policy hash must be a lowercase SHA-256 value")
        return value.strip()

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
        self.validate_provider_configuration()
        # Parse the complete private graph before the application lifespan
        # yields. A malformed catalog therefore prevents readiness rather
        # than partially applying identities.
        if self.demo_mode or self.demo_quick_login or self.resolved_demo_accounts_file.exists():
            from app.modules.auth.credentials import prepare_catalog

            prepare_catalog(self)

    def validate_provider_configuration(self) -> None:
        """Allow Mock, one real slice, or the frozen dual Real-Core pair.

        The only multi-real composition admitted by the Demo is DashScope
        Embedding plus DashScope LLM with Mock/disabled companions.  Each
        endpoint-bound slice has its own policy hash.  The LLM adapter still
        requires its own runtime confirmation/operation gate before any
        request; selector construction alone performs no network I/O.
        """

        selectors = (
            self.llm_provider,
            self.report_provider,
            self.embedding_provider,
            self.tts_provider,
            self.voice_provider,
        )
        if any(value not in {"mock", "dashscope"} for value in selectors):
            raise RuntimeError("provider selector is not supported")

        non_mock = [
            name for name, value in (("VOICE_PROVIDER", self.voice_provider),) if value != "mock"
        ]
        if non_mock:
            raise RuntimeError(
                "runtime provider gate permits only one reviewed DashScope slice with "
                "Mock companions: " + ", ".join(non_mock)
            )
        real_slice_names = tuple(
            name
            for name, value in (
                ("LLM_PROVIDER", self.llm_provider),
                ("REPORT_PROVIDER", self.report_provider),
                ("EMBEDDING_PROVIDER", self.embedding_provider),
                ("TTS_PROVIDER", self.tts_provider),
            )
            if value == "dashscope"
        )
        allowed_real_compositions = {
            (),
            ("EMBEDDING_PROVIDER",),
            ("LLM_PROVIDER",),
            ("TTS_PROVIDER",),
            ("LLM_PROVIDER", "EMBEDDING_PROVIDER"),
            ("REPORT_PROVIDER",),
            ("LLM_PROVIDER", "REPORT_PROVIDER"),
            ("REPORT_PROVIDER", "EMBEDDING_PROVIDER"),
            ("LLM_PROVIDER", "REPORT_PROVIDER", "EMBEDDING_PROVIDER"),
        }
        if real_slice_names not in allowed_real_compositions:
            raise RuntimeError(
                "runtime provider gate permits only the Real Embedding + Real LLM pair "
                "or one reviewed DashScope slice with Mock companions"
            )
        if real_slice_names:
            if not self.dashscope_api_key or not self.dashscope_api_key.strip():
                raise RuntimeError(
                    "DASHSCOPE_API_KEY is required for real Provider work; "
                    "Mock companions remain the default"
                )
            if not self.dashscope_workspace_id or not self.dashscope_workspace_id.strip():
                raise RuntimeError(
                    "DASHSCOPE_WORKSPACE_ID is required for real Provider work; "
                    "Mock companions remain the default"
                )
            if self.dashscope_region != "cn-beijing":
                raise RuntimeError(
                    "DASHSCOPE_REGION must be cn-beijing for real Provider work; "
                    "Mock companions remain the default"
                )
        # A legacy PROVIDER_POLICY_HASH is endpoint-ambiguous when both real
        # slices are selected.  Require the two explicit fields in that case;
        # a single-real configuration may still use the old field.
        if len(real_slice_names) == 2 and set(real_slice_names) == {
            "LLM_PROVIDER",
            "EMBEDDING_PROVIDER",
        }:
            if self.provider_policy_hash is not None and not (
                self.embedding_provider_policy_hash is not None
                and self.llm_provider_policy_hash is not None
            ):
                raise RuntimeError(
                    "dual real Provider work requires separate "
                    "EMBEDDING_PROVIDER_POLICY_HASH and LLM_PROVIDER_POLICY_HASH"
                )
            if self.embedding_provider_policy_hash is None:
                raise RuntimeError(
                    "EMBEDDING_PROVIDER_POLICY_HASH is required for real Embedding publication"
                )
            if self.llm_provider_policy_hash is None:
                raise RuntimeError("LLM_PROVIDER_POLICY_HASH is required for real LLM publication")
        elif self.embedding_provider == "dashscope" and self.embedding_policy_hash is None:
            raise RuntimeError(
                "EMBEDDING_PROVIDER_POLICY_HASH (or an unambiguous legacy "
                "PROVIDER_POLICY_HASH) is required for real Embedding publication"
            )
        elif self.llm_provider == "dashscope" and self.llm_policy_hash is None:
            raise RuntimeError(
                "LLM_PROVIDER_POLICY_HASH (or an unambiguous legacy "
                "PROVIDER_POLICY_HASH) is required for real LLM publication"
            )
        if self.report_provider == "dashscope" and self.report_policy_hash is None:
            raise RuntimeError(
                "REPORT_PROVIDER_POLICY_HASH is required for real Maya Report publication"
            )

    @property
    def embedding_policy_hash(self) -> str | None:
        """Return the hash bound to real Embedding, with legacy compatibility."""

        if self.embedding_provider_policy_hash is not None:
            return self.embedding_provider_policy_hash
        if self.provider_policy_hash is not None and self.embedding_provider == "dashscope":
            if self.llm_provider != "dashscope":
                return self.provider_policy_hash
        return None

    @property
    def llm_policy_hash(self) -> str | None:
        """Return the hash bound to real LLM, with legacy compatibility."""

        if self.llm_provider_policy_hash is not None:
            return self.llm_provider_policy_hash
        if self.provider_policy_hash is not None and self.llm_provider == "dashscope":
            if self.embedding_provider != "dashscope":
                return self.provider_policy_hash
        return None

    @property
    def report_policy_hash(self) -> str | None:
        """Return the endpoint policy hash bound to Real Maya Report."""

        if self.report_provider_policy_hash is not None:
            return self.report_provider_policy_hash
        if self.provider_policy_hash is not None and self.report_provider == "dashscope":
            if self.llm_provider != "dashscope" and self.embedding_provider != "dashscope":
                return self.provider_policy_hash
        return None

    def provider_policy_hash_for(self, slice_name: str) -> str | None:
        """Resolve an endpoint policy hash without silently crossing slices."""

        if slice_name == "embedding":
            return self.embedding_policy_hash
        if slice_name == "llm":
            return self.llm_policy_hash
        if slice_name == "report":
            return self.report_policy_hash
        raise ValueError("provider policy slice must be embedding, llm or report")

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
    def classroom_public_origin(self) -> str | None:
        """Return a phone-reachable private-LAN origin or ``None``.

        Loopback is valid for the ordinary local site but cannot be placed in
        a QR code: a phone would resolve it to itself.  Wave 3 deliberately
        accepts only a private numeric address or a local-network hostname.
        """

        value = self.classroom_public_base_url
        if value is None:
            return None
        hostname = (urlsplit(value).hostname or "").lower().rstrip(".")
        if hostname == "localhost":
            return None
        try:
            address = ip_address(hostname)
        except ValueError:
            return value if hostname.endswith(".local") else None
        private_networks = (
            ip_network("10.0.0.0/8"),
            ip_network("172.16.0.0/12"),
            ip_network("192.168.0.0/16"),
            ip_network("fc00::/7"),
        )
        return value if any(address in network for network in private_networks) else None

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

    @property
    def resolved_demo_accounts_file(self) -> Path:
        path = self.demo_accounts_file
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[2] / path

    @property
    def resolved_config_root(self) -> Path:
        """Where private operator files live, outside the disposable runtime.

        Derived from the accounts file so a container mounting ``/app/config``
        and a host checkout both resolve to the same directory.
        """

        return self.resolved_demo_accounts_file.parent.parent

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


def configured_llm_model() -> str:
    """Chat, debate and report model. One env value, not a per-surface id."""

    return get_settings().llm_model
