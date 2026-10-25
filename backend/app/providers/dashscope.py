"""Server-only DashScope adapters.

These adapters are never selected implicitly.  A caller must explicitly set a
server selector to ``dashscope`` and provide credentials; CI and local Demo
defaults use the Mock adapters from :mod:`app.providers.factory`.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.request_timing import provider_call
from app.providers.audio import MAX_PREVIEW_BYTES, AudioValidationError, validate_speech_audio
from app.providers.tts import (
    TTSAudioInvalidError,
    TTSHTTPRejectedError,
    TTSProviderError,
    TTSProviderTimeout,
    TTSResponseInvalidError,
    TTSResult,
    TTSResultDNSFailedError,
    TTSResultDownloadError,
    TTSResultURLRejectedError,
    TTSVoiceUnavailableError,
)
from app.providers.voice import (
    VoiceCloneRefusedError,
    VoiceEnrollmentResult,
    VoiceExistenceResult,
    VoiceProviderError,
    VoiceProviderTimeout,
)

# The supplier retired this clone model in October 2026. Clones enrolled on it
# can no longer speak; their owners delete and record them again.
LEGACY_CLONE_MODEL_KEY = "qwen3-tts-vc-2026-01-22"
LEGACY_VOICE_ENROLLMENT_MODEL = "qwen-voice-enrollment"
# Stored on the Eldric Sage preset row, whose encrypted envelope binds this
# key, so the row keeps it. It is never sent: every system voice speaks
# through FLASH_TTS_MODEL_KEY.
PRESET_TTS_MODEL_KEY = "qwen3-tts-flash-2025-11-27"
FLASH_TTS_MODEL_KEY = "qwen3-tts-flash"
SYSTEM_VOICE_MODEL_KEYS = frozenset({PRESET_TTS_MODEL_KEY, FLASH_TTS_MODEL_KEY})
# Clone targets the operator may choose with VOICE_CLONE_MODEL; first is default.
CLONE_TTS_MODEL_KEYS = ("qwen-audio-3.1-tts-flash", "qwen-audio-3.0-tts-flash")
DEFAULT_TARGET_MODEL_KEY = CLONE_TTS_MODEL_KEYS[0]
ALLOWED_TTS_TARGET_MODELS = SYSTEM_VOICE_MODEL_KEYS | frozenset(CLONE_TTS_MODEL_KEYS)
# Official published system voices for qwen3-tts-flash (Model Studio list).
# Clone / enrollment ids are never on this list; the flash path refuses them.
FLASH_SYSTEM_VOICES = frozenset(
    {
        "Aiden",
        "Alek",
        "Andre",
        "Arthur",
        "Bella",
        "Bellona",
        "Bodega",
        "Bunny",
        "Chelsie",
        "Cherry",
        "Dolce",
        "Dylan",
        "Eldric Sage",
        "Elias",
        "Emilien",
        "Eric",
        "Ethan",
        "Jada",
        "Jennifer",
        "Kai",
        "Katerina",
        "Kiki",
        "Lenn",
        "Li",
        "Maia",
        "Marcus",
        "Mia",
        "Mochi",
        "Momo",
        "Moon",
        "Neil",
        "Nini",
        "Nofish",
        "Ono Anna",
        "Peter",
        "Pip",
        "Radio Gol",
        "Rocky",
        "Roy",
        "Ryan",
        "Seren",
        "Serena",
        "Sohee",
        "Sonrisa",
        "Stella",
        "Sunny",
        "Vincent",
        "Vivian",
    }
)
TTS_FLASH_MAX_CHARS = 600
VOICE_ENROLLMENT_MODEL = "voice-enrollment"
APPROVED_RESULT_HOST_SUFFIXES = (
    "dashscope.aliyuncs.com",
    "dashscope-result-bj.oss-cn-beijing.aliyuncs.com",
)
# The Qwen non-streaming HTTP API currently documents its signed Beijing OSS
# result URL with an ``http`` scheme even though the object store supports
# HTTPS.  This is deliberately an exact host allowlist: an arbitrary HTTP
# URL must never become eligible merely because it can be rewritten to HTTPS.
OFFICIAL_HTTP_RESULT_HOSTS = frozenset({"dashscope-result-bj.oss-cn-beijing.aliyuncs.com"})
VOICE_CUSTOMIZATION_PATH = "/api/v1/services/audio/tts/customization"
TTS_GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
# Qwen-Audio-TTS clones speak through the SpeechSynthesizer HTTP API.
SPEECH_SYNTHESIZER_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
# Voice enrollment for Qwen-Audio-TTS reads its sample from a URL, so the
# sample goes to DashScope's temporary upload store first.
UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
UPLOAD_HOST_SUFFIX = ".aliyuncs.com"
# A new clone is reviewed before it can speak; wait a bounded time for it.
VOICE_REVIEW_WAIT_SECONDS = 20.0
VOICE_REVIEW_POLL_SECONDS = 2.0
TTS_GENERATION_READ_TIMEOUT_SECONDS = 120.0
# Qwen-TTS uses the shared Beijing endpoint; the request header retains
# the workspace that owns the enrolled voice.
QWEN_TTS_URL = f"https://dashscope.aliyuncs.com{TTS_GENERATION_PATH}"


@dataclass(frozen=True)
class DashScopeConfig:
    api_key: str
    workspace_id: str
    region: str = "cn-beijing"
    target_model_key: str = DEFAULT_TARGET_MODEL_KEY


def _safe_workspace(workspace_id: str) -> str:
    if not workspace_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in workspace_id
    ):
        raise VoiceProviderError("provider is not configured")
    return workspace_id


def _base_url(config: DashScopeConfig) -> str:
    if config.region != "cn-beijing" or not config.api_key:
        raise VoiceProviderError("provider is not configured")
    workspace = _safe_workspace(config.workspace_id)
    return f"https://{workspace}.cn-beijing.maas.aliyuncs.com"


def _client(*, read_timeout: float = 30.0) -> httpx.Client:
    timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=30.0, pool=10.0)
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code < 200 or response.status_code >= 300:
        raise VoiceProviderError("provider request failed")
    try:
        value = response.json()
    except (TypeError, ValueError) as exc:
        raise VoiceProviderError("provider response invalid") from exc
    if not isinstance(value, dict):
        raise VoiceProviderError("provider response invalid")
    return value


def tts_model_for_call(configured: str, requested: str | None) -> str:
    """Return the model for one TTS request, or refuse before any network I/O.

    ``None`` keeps the adapter default, which is the clone model. System
    voices always speak through the flash alias. A clone on the retired model
    is unavailable rather than guessed onto a new model it was never enrolled
    for. Anything else is not guessed into a request.
    """

    model = configured if requested is None else requested
    if model in SYSTEM_VOICE_MODEL_KEYS:
        return FLASH_TTS_MODEL_KEY
    if model in CLONE_TTS_MODEL_KEYS:
        return model
    if model == LEGACY_CLONE_MODEL_KEY:
        raise TTSVoiceUnavailableError("tts voice retired")
    raise TTSProviderError("unsupported tts model", safe_code="tts_response_invalid")


def _tts_json(response: httpx.Response) -> dict[str, Any]:
    """Parse a TTS response with a TTS-specific safe classification."""

    if response.status_code < 200 or response.status_code >= 300:
        raise TTSHTTPRejectedError("provider request failed")
    try:
        value = response.json()
    except (TypeError, ValueError) as exc:
        raise TTSResponseInvalidError("provider response invalid") from exc
    if not isinstance(value, dict):
        raise TTSResponseInvalidError("provider response invalid")
    return value


def _request_id(response: httpx.Response, document: dict[str, Any] | None = None) -> str | None:
    value = (document or {}).get("request_id")
    if not isinstance(value, str):
        value = response.headers.get("x-request-id") or response.headers.get("request-id")
    if value is None or len(value) > 120:
        return None
    return value if all(ord(char) >= 32 and ord(char) < 127 for char in value) else None


def _sample_bytes(audio_data_uri: str) -> bytes:
    """Decode the normalized WAV sample the service hands to ``enroll``."""

    prefix = "data:audio/wav;base64,"
    if not audio_data_uri.startswith(prefix):
        raise VoiceProviderError("provider request invalid")
    try:
        return b64decode(audio_data_uri[len(prefix) :], validate=True)
    except (BinasciiError, ValueError) as exc:
        raise VoiceProviderError("provider request invalid") from exc


def _upload_policy(document: dict[str, Any]) -> dict[str, str]:
    data = document.get("data")
    if not isinstance(data, dict):
        raise VoiceProviderError("provider response invalid")
    fields = (
        "policy",
        "signature",
        "upload_dir",
        "upload_host",
        "oss_access_key_id",
        "x_oss_object_acl",
        "x_oss_forbid_overwrite",
    )
    policy: dict[str, str] = {}
    for field in fields:
        value = data.get(field)
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise VoiceProviderError("provider response invalid")
        policy[field] = value
    host = urlsplit(policy["upload_host"])
    # The upload target comes from the supplier response: only its own HTTPS
    # object store may receive the sample.
    if (
        host.scheme != "https"
        or not host.hostname
        or not host.hostname.endswith(UPLOAD_HOST_SUFFIX)
        or host.username
        or host.password
        or ".." in policy["upload_dir"]
        or policy["upload_dir"].startswith("/")
    ):
        raise VoiceProviderError("provider response invalid")
    return policy


class DashScopeVoiceCloneProvider:
    """DashScope voice enrollment/existence/delete adapter.

    New clones enroll for a Qwen-Audio-TTS model through ``voice-enrollment``.
    Clones on the retired model keep their old list/delete API so their owners
    can still delete them.
    """

    key = "dashscope"

    def __init__(self, config: DashScopeConfig) -> None:
        self.config = config
        self.target_model_key = config.target_model_key

    def _upload_sample(self, client: httpx.Client, sample: bytes, recovery_name: str) -> str:
        """Put the sample in DashScope's temporary store and return its oss:// URL."""

        workspace = _safe_workspace(self.config.workspace_id)
        response = client.get(
            UPLOAD_POLICY_URL,
            params={"action": "getPolicy", "model": VOICE_ENROLLMENT_MODEL},
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "X-DashScope-WorkSpace": workspace,
            },
        )
        policy = _upload_policy(_json(response))
        key = f"{policy['upload_dir']}/{recovery_name}.wav"
        uploaded = client.post(
            policy["upload_host"],
            data={
                "OSSAccessKeyId": policy["oss_access_key_id"],
                "Signature": policy["signature"],
                "policy": policy["policy"],
                "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
                "key": key,
                "success_action_status": "200",
            },
            files={"file": (f"{recovery_name}.wav", sample, "audio/wav")},
        )
        if uploaded.status_code < 200 or uploaded.status_code >= 300:
            raise VoiceProviderError("provider request failed")
        return f"oss://{key}"

    def enroll(
        self,
        audio_data_uri: str,
        *,
        recovery_name: str,
        target_model_key: str,
        language: str = "en",
        transcript: str | None = None,
    ) -> VoiceEnrollmentResult:
        # System voices are supplier names and the retired clone model takes
        # no new voices; only a Qwen-Audio-TTS target may be enrolled.
        if target_model_key not in CLONE_TTS_MODEL_KEYS:
            raise VoiceCloneRefusedError("model does not support enrollment")
        # Qwen-Audio-TTS enrollment reads the sample alone.
        del language, transcript
        sample = _sample_bytes(audio_data_uri)
        try:
            with _client() as client, provider_call("voice"):
                audio_url = self._upload_sample(client, sample, recovery_name)
                response = client.post(
                    f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "X-DashScope-OssResourceResolve": "enable",
                    },
                    json={
                        "model": VOICE_ENROLLMENT_MODEL,
                        "input": {
                            "action": "create_voice",
                            "target_model": target_model_key,
                            "prefix": recovery_name,
                            "url": audio_url,
                        },
                    },
                )
            document = _json(response)
        except httpx.TimeoutException as exc:
            raise VoiceProviderTimeout("provider request timed out") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise VoiceProviderError("provider request failed") from exc
        finally:
            sample = b""
        output = document.get("output")
        if not isinstance(output, dict):
            raise VoiceProviderError("provider response invalid")
        value = output.get("voice_id")
        if not isinstance(value, str) or not value or len(value) > 512:
            raise VoiceProviderError("provider response invalid")
        if self._review_status(value) == "UNDEPLOYED":
            # The supplier's review rejected the sample. Free the slot it holds
            # in the workspace quota; the profile becomes a refused card.
            try:
                self.delete(value, target_model_key=target_model_key)
            except VoiceProviderError:
                pass
            raise VoiceCloneRefusedError("voice rejected by supplier review")
        return VoiceEnrollmentResult(
            external_voice_id=value,
            request_id=_request_id(response, document),
            input_bytes=len(audio_data_uri.encode("utf-8")),
            charged=True,
            degraded=False,
        )

    def _review_status(self, voice_id: str) -> str | None:
        """Wait briefly for the supplier's review of a new clone.

        A new voice is reviewed before it can speak. ``OK`` and ``UNDEPLOYED``
        are final. A voice still under review after the wait is returned as
        created: its preview fails until review ends and Retry then works.
        """

        deadline = time.monotonic() + VOICE_REVIEW_WAIT_SECONDS
        status: str | None = None
        try:
            with _client() as client, provider_call("voice"):
                while True:
                    response = client.post(
                        f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                        json={
                            "model": VOICE_ENROLLMENT_MODEL,
                            "input": {"action": "query_voice", "voice_id": voice_id},
                        },
                    )
                    output = _json(response).get("output")
                    value = output.get("status") if isinstance(output, dict) else None
                    status = value if isinstance(value, str) else None
                    if status in {"OK", "UNDEPLOYED"}:
                        return status
                    if time.monotonic() + VOICE_REVIEW_POLL_SECONDS > deadline:
                        return status
                    time.sleep(VOICE_REVIEW_POLL_SECONDS)
        except (httpx.HTTPError, OSError, VoiceProviderError):
            # The voice exists either way; a failed status read must not turn
            # a charged create into a lost one.
            return status

    def exists(
        self,
        recovery_name: str,
        *,
        target_model_key: str,
    ) -> VoiceExistenceResult:
        legacy = target_model_key == LEGACY_CLONE_MODEL_KEY
        matches: list[str] = []
        visibility_known = False
        page_size = 100
        try:
            with _client() as client, provider_call("voice"):
                # Pagination is intentionally private to this adapter.  Only
                # recovery-name matches leave this method.
                for page in range(10):
                    request_input: dict[str, Any] = (
                        {"action": "list", "page_index": page, "page_size": page_size}
                        if legacy
                        else {
                            "action": "list_voice",
                            "prefix": recovery_name,
                            "page_index": page,
                            "page_size": page_size,
                        }
                    )
                    response = client.post(
                        f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                        json={
                            "model": (
                                LEGACY_VOICE_ENROLLMENT_MODEL if legacy else VOICE_ENROLLMENT_MODEL
                            ),
                            "input": request_input,
                        },
                    )
                    document = _json(response)
                    output = document.get("output", document)
                    rows = output.get("voice_list", []) if isinstance(output, dict) else output
                    if not isinstance(rows, list):
                        raise VoiceProviderError("provider response invalid")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        voice = row.get("voice" if legacy else "voice_id")
                        if not isinstance(voice, str) or not voice or len(voice) > 512:
                            continue
                        # Qwen-Audio-TTS ids read <model>-<prefix>-<suffix>.
                        if legacy and not voice.startswith(recovery_name):
                            continue
                        if not legacy and f"-{recovery_name}-" not in voice:
                            continue
                        if row.get("target_model") not in {None, target_model_key}:
                            continue
                        matches.append(voice)
                    total_count = output.get("total_count") if isinstance(output, dict) else None
                    if len(rows) < page_size:
                        visibility_known = True
                        break
                    if (
                        isinstance(total_count, int)
                        and not isinstance(total_count, bool)
                        and total_count >= 0
                        and (page + 1) * page_size >= total_count
                    ):
                        visibility_known = True
                        break
        except httpx.TimeoutException as exc:
            raise VoiceProviderTimeout("provider request timed out") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise VoiceProviderError("provider request failed") from exc
        return VoiceExistenceResult(
            tuple(dict.fromkeys(matches)), visibility_known=visibility_known
        )

    def delete(self, external_voice_id: str, *, target_model_key: str) -> None:
        payload = (
            {
                "model": LEGACY_VOICE_ENROLLMENT_MODEL,
                "input": {"action": "delete", "voice": external_voice_id},
            }
            if target_model_key == LEGACY_CLONE_MODEL_KEY
            else {
                "model": VOICE_ENROLLMENT_MODEL,
                "input": {"action": "delete_voice", "voice_id": external_voice_id},
            }
        )
        try:
            with _client() as client, provider_call("voice"):
                response = client.post(
                    f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
            _json(response)
        except httpx.TimeoutException as exc:
            raise VoiceProviderTimeout("provider request timed out") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise VoiceProviderError("provider request failed") from exc


def _is_approved_host(hostname: str, suffixes: tuple[str, ...]) -> bool:
    # DNS absolute-name notation (a trailing dot) is deliberately not
    # accepted.  The caller later pins the resolved address, so the URL
    # authority must remain the exact allowlisted spelling.
    lowered = hostname.lower()
    return any(lowered == suffix or lowered.endswith("." + suffix) for suffix in suffixes)


def _resolved_public_addresses(hostname: str, *, timeout_seconds: float = 10.0) -> tuple[str, ...]:
    result: list[Any] = []

    def resolve() -> None:
        try:
            result.append(socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM))
        except OSError as exc:
            result.append(exc)

    worker = threading.Thread(target=resolve, daemon=True, name="maya-supplier-dns")
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TTSProviderTimeout("supplier host resolution timed out")
    if not result or isinstance(result[0], OSError):
        raise TTSResultDNSFailedError("supplier host unavailable")
    infos = result[0]
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise TTSResultDNSFailedError("supplier host unavailable") from exc
        if not parsed.is_global:
            raise TTSResultDNSFailedError("supplier host unavailable")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise TTSResultDNSFailedError("supplier host unavailable")
    return tuple(addresses)


def validate_supplier_url(
    value: str,
    *,
    allowed_suffixes: tuple[str, ...] = APPROVED_RESULT_HOST_SUFFIXES,
) -> str:
    """Validate supplier URL shape before any network operation."""

    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise TTSResultURLRejectedError("supplier URL rejected") from exc
    if (
        parsed.scheme.lower() != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or "#" in value
        or port is not None
        or ":" in parsed.netloc.rsplit("@", 1)[-1]
        or not _is_approved_host(host, allowed_suffixes)
    ):
        raise TTSResultURLRejectedError("supplier URL rejected")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise TTSResultURLRejectedError("supplier URL rejected")
    return value


def _upgrade_official_result_url(value: str) -> str:
    """Upgrade the documented Beijing OSS result URL to HTTPS in memory.

    Qwen's non-streaming response examples use an ``http`` URL for the
    signed WAV object.  The downloader is intentionally HTTPS-only because a
    signed URL contains bearer-like query material, so only the exact
    provider-owned Beijing result host is eligible for this compatibility
    rewrite.  URL validation still runs after the rewrite and rejects
    userinfo, fragments, non-443 ports, IP literals and private DNS results.
    """

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise TTSResultURLRejectedError("supplier URL rejected") from exc
    if parsed.scheme.lower() != "http":
        return value
    # Only the documented lowercase Beijing result authority may be upgraded.
    # Do not normalize case, remove a trailing dot, preserve userinfo, or
    # carry an explicit port into the HTTPS URL.
    if (
        not value.startswith("http://")
        or hostname is None
        or parsed.netloc not in OFFICIAL_HTTP_RESULT_HOSTS
        or hostname not in OFFICIAL_HTTP_RESULT_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or "#" in value
        or port is not None
        or ":" in parsed.netloc.rsplit("@", 1)[-1]
    ):
        raise TTSResultURLRejectedError("supplier URL rejected")
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def _remaining_timeout(deadline: float, cap: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TTSProviderTimeout("supplier audio timed out")
    return min(cap, remaining)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection whose TCP peer is an already-approved numeric address."""

    def __init__(self, hostname: str, address: str, deadline: float) -> None:
        self._ssl_context = ssl.create_default_context()
        self._deadline = deadline
        super().__init__(
            hostname,
            port=443,
            timeout=_remaining_timeout(deadline, 30.0),
            context=self._ssl_context,
        )
        self._pinned_address = address

    def connect(self) -> None:
        parsed = ipaddress.ip_address(self._pinned_address)
        family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        try:
            raw_socket.settimeout(_remaining_timeout(self._deadline, 10.0))
            destination: tuple[Any, ...]
            if parsed.version == 6:
                destination = (self._pinned_address, 443, 0, 0)
            else:
                destination = (self._pinned_address, 443)
            raw_socket.connect(destination)
            wrapped = self._ssl_context.wrap_socket(raw_socket, server_hostname=self.host)
            peer = str(wrapped.getpeername()[0])
            if ipaddress.ip_address(peer) != parsed:
                wrapped.close()
                raise TTSResultDownloadError("supplier host changed")
            wrapped.settimeout(_remaining_timeout(self._deadline, 30.0))
            self.sock = wrapped
        except BaseException:
            raw_socket.close()
            raise


def _download_from_pinned_address(
    url: str,
    hostname: str,
    address: str,
    *,
    max_bytes: int,
    deadline: float,
) -> bytes:
    """Issue GET only after TLS is established to the approved numeric peer."""

    parsed = urlsplit(url)
    request_target = parsed.path or "/"
    if parsed.query:
        request_target += "?" + parsed.query
    with provider_call("tts"):
        return _download_pinned(request_target, hostname, address, max_bytes, deadline)


def _download_pinned(
    request_target: str,
    hostname: str,
    address: str,
    max_bytes: int,
    deadline: float,
) -> bytes:
    connection = _PinnedHTTPSConnection(hostname, address, deadline)
    try:
        if connection.sock is not None:
            connection.sock.settimeout(_remaining_timeout(deadline, 30.0))
        connection.request(
            "GET",
            request_target,
            headers={"Host": hostname, "Accept": "audio/*", "Connection": "close"},
        )
        if connection.sock is not None:
            connection.sock.settimeout(_remaining_timeout(deadline, 30.0))
        response = connection.getresponse()
        if response.status != 200:
            raise TTSResultDownloadError("supplier audio unavailable")
        content_length = response.getheader("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_bytes:
                    raise TTSResultDownloadError("supplier audio too large")
            except ValueError as exc:
                raise TTSResultDownloadError("supplier audio invalid") from exc
        chunks: list[bytes] = []
        total = 0
        while True:
            if connection.sock is not None:
                connection.sock.settimeout(_remaining_timeout(deadline, 30.0))
            chunk = response.read(min(64 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise TTSResultDownloadError("supplier audio too large")
            chunks.append(chunk)
        return b"".join(chunks)
    except TimeoutError as exc:
        raise TTSProviderTimeout("supplier audio timed out") from exc
    except TTSProviderError:
        raise
    except (http.client.HTTPException, ssl.SSLError, OSError) as exc:
        raise TTSResultDownloadError("supplier audio unavailable") from exc
    finally:
        connection.close()


class SupplierAudioDownloader:
    """HTTPS-only bounded downloader pinned to a pre-approved public address."""

    def __init__(self, *, max_bytes: int = MAX_PREVIEW_BYTES) -> None:
        self.max_bytes = max_bytes

    def download(self, value: str) -> bytes:
        # The supplier's documented Qwen result URL is HTTP; upgrade only
        # the exact Beijing result host before the common HTTPS/SSRF checks.
        url = validate_supplier_url(_upgrade_official_result_url(value))
        parsed = urlsplit(url)
        if parsed.hostname is None:  # pragma: no cover - validated above
            raise TTSResultURLRejectedError("supplier URL rejected")
        deadline = time.monotonic() + 60.0
        approved_addresses = _resolved_public_addresses(parsed.hostname)
        _remaining_timeout(deadline, 60.0)
        last_error: TTSProviderError | None = None
        for address in approved_addresses:
            _remaining_timeout(deadline, 60.0)
            try:
                result = _download_from_pinned_address(
                    url,
                    parsed.hostname,
                    address,
                    max_bytes=self.max_bytes,
                    deadline=deadline,
                )
            except TTSProviderTimeout:
                raise
            except TTSProviderError as exc:
                last_error = exc
                continue
            if not result:
                raise TTSResultDownloadError("supplier audio invalid")
            return result
        raise last_error or TTSResultDownloadError("supplier audio unavailable")


# Qwen VC writes a finished WAV whose RIFF and data sizes stay near 2**31.
# A real download is capped at 20 MiB, so a declared size of at least 1 GiB
# cannot be a length — it is that placeholder. A merely truncated file keeps
# a small declared size and must still fail the strict check.
_STREAMED_WAV_PLACEHOLDER = 1 << 30
# Mixed-language voice previews explicitly select Auto; unknown codes still fail closed.
_TTS_LANGUAGE_TYPES = {"en": "English", "zh": "Chinese", "auto": "Auto"}


def _finalize_streamed_wav(raw: bytes) -> bytes:
    """Fill in RIFF/data sizes the supplier leaves as streaming placeholders.

    Only a RIFF/WAVE whose earlier chunks fit, whose last chunk is ``data``,
    and whose RIFF and data sizes are both streaming placeholders is rewritten.
    The strict technical audio check still runs on the result.
    """

    if len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw
    riff_size = int.from_bytes(raw[4:8], "little")
    if riff_size < _STREAMED_WAV_PLACEHOLDER:
        return raw
    offset = 12
    while len(raw) - offset >= 8:
        chunk_id = raw[offset : offset + 4]
        chunk_size = int.from_bytes(raw[offset + 4 : offset + 8], "little")
        body = offset + 8
        if chunk_id == b"data":
            remaining = len(raw) - body
            if chunk_size < _STREAMED_WAV_PLACEHOLDER or chunk_size <= remaining:
                return raw
            remaining -= remaining % 2
            if remaining <= 0:
                return raw
            fixed = bytearray(raw[: body + remaining])
            fixed[offset + 4 : offset + 8] = remaining.to_bytes(4, "little")
            fixed[4:8] = (len(fixed) - 8).to_bytes(4, "little")
            return bytes(fixed)
        padded = body + chunk_size + (chunk_size % 2)
        if chunk_size >= _STREAMED_WAV_PLACEHOLDER or padded > len(raw):
            return raw
        offset = padded
    return raw


# SpeechSynthesizer ``input`` fields a qwen-audio-*-tts-flash clone accepts.
_CLONE_VOICE_FIELDS = ("rate", "instruction", "seed")


def _clone_voice_fields(params: Mapping[str, object] | None) -> dict[str, object]:
    """rate / instruction / seed that are set; an empty value is not sent."""

    fields: dict[str, object] = {}
    for name in _CLONE_VOICE_FIELDS:
        value = (params or {}).get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        fields[name] = value.strip() if isinstance(value, str) else value
    return fields


class DashScopeTTSProvider:
    """DashScope non-streaming TTS adapter with bounded result download."""

    key = "dashscope"

    def __init__(
        self,
        config: DashScopeConfig,
        downloader: SupplierAudioDownloader | None = None,
    ) -> None:
        self.config = config
        self.target_model_key = config.target_model_key
        self.downloader = downloader or SupplierAudioDownloader()

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
        voice_params: Mapping[str, object] | None = None,
    ) -> TTSResult:
        language_type = _TTS_LANGUAGE_TYPES.get(language)
        if language_type is None:
            raise TTSProviderError("unsupported language")
        model = tts_model_for_call(self.target_model_key, target_model_key)
        if self.config.region != "cn-beijing" or not self.config.api_key:
            raise VoiceProviderError("provider is not configured")
        workspace = _safe_workspace(self.config.workspace_id)
        if model == FLASH_TTS_MODEL_KEY:
            # Zero outbound for a name the flash model does not publish or
            # text over its input limit.
            if external_voice_id not in FLASH_SYSTEM_VOICES:
                raise TTSVoiceUnavailableError("tts voice unavailable")
            if len(text) > TTS_FLASH_MAX_CHARS:
                raise TTSProviderError("tts text too long", safe_code="tts_response_invalid")
            url = QWEN_TTS_URL
            payload: dict[str, Any] = {
                "model": model,
                "input": {
                    "text": text,
                    "voice": external_voice_id,
                    "language_type": language_type,
                },
            }
        else:
            # A Qwen-Audio-TTS clone detects the language from the text.
            url = f"{_base_url(self.config)}{SPEECH_SYNTHESIZER_PATH}"
            payload = {
                "model": model,
                "input": {
                    "text": text,
                    "voice": external_voice_id,
                    "format": "wav",
                    "sample_rate": 24000,
                    # Cloned voices only: the preset flash model above takes
                    # text, voice and language_type alone.
                    **_clone_voice_fields(voice_params),
                },
            }
        try:
            # Cloned synthesis can take longer than the generic provider read window.
            with (
                _client(read_timeout=TTS_GENERATION_READ_TIMEOUT_SECONDS) as client,
                provider_call("tts"),
            ):
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "X-DashScope-WorkSpace": workspace,
                    },
                    json=payload,
                )
            document = _tts_json(response)
        except httpx.TimeoutException as exc:
            raise TTSProviderTimeout("provider request timed out") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise TTSHTTPRejectedError("provider request failed") from exc
        output = document.get("output")
        audio = output.get("audio") if isinstance(output, dict) else None
        audio_url = audio.get("url") if isinstance(audio, dict) else None
        if not isinstance(audio_url, str) or not audio_url:
            raise TTSResponseInvalidError("provider response invalid")
        raw = _finalize_streamed_wav(self.downloader.download(audio_url))
        try:
            validate_speech_audio(raw)
        except AudioValidationError as exc:
            raise TTSAudioInvalidError("provider audio invalid") from exc
        return TTSResult(raw, "audio/wav", _request_id(response, document))
