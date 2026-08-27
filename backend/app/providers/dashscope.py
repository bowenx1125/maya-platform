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
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.providers.audio import MAX_PREVIEW_BYTES, AudioValidationError, validate_technical_audio
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
)
from app.providers.voice import (
    VoiceEnrollmentResult,
    VoiceExistenceResult,
    VoiceProviderError,
    VoiceProviderTimeout,
)

DEFAULT_TARGET_MODEL_KEY = "qwen3-tts-vc-2026-01-22"
VOICE_ENROLLMENT_MODEL = "qwen-voice-enrollment"
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
# Kept as a documented shared-endpoint reference for callers that need to
# compare the provider's public API shape.  Actual TTS requests use the
# workspace endpoint derived from ``_base_url`` below.
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


def _client() -> httpx.Client:
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0)
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


class DashScopeVoiceCloneProvider:
    """DashScope voice enrollment/existence/delete adapter."""

    key = "dashscope"

    def __init__(self, config: DashScopeConfig) -> None:
        self.config = config
        self.target_model_key = config.target_model_key

    def enroll(
        self,
        audio_data_uri: str,
        *,
        recovery_name: str,
        target_model_key: str,
        language: str = "en",
        transcript: str | None = None,
    ) -> VoiceEnrollmentResult:
        payload: dict[str, Any] = {
            "model": VOICE_ENROLLMENT_MODEL,
            "input": {
                "action": "create",
                "target_model": target_model_key,
                "preferred_name": recovery_name,
                "audio": {"data": audio_data_uri},
                "language": language,
            },
        }
        if transcript:
            payload["input"]["text"] = transcript
        try:
            with _client() as client:
                response = client.post(
                    f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
            document = _json(response)
        except httpx.TimeoutException as exc:
            raise VoiceProviderTimeout("provider request timed out") from exc
        except (httpx.HTTPError, OSError) as exc:
            raise VoiceProviderError("provider request failed") from exc
        output = document.get("output")
        if not isinstance(output, dict):
            raise VoiceProviderError("provider response invalid")
        value = output.get("voice")
        if not isinstance(value, str) or not value or len(value) > 512:
            raise VoiceProviderError("provider response invalid")
        return VoiceEnrollmentResult(
            external_voice_id=value,
            request_id=_request_id(response, document),
            input_bytes=len(audio_data_uri.encode("utf-8")),
            charged=True,
            degraded=output.get("fallback_mode") is True,
        )

    def exists(
        self,
        recovery_name: str,
        *,
        target_model_key: str,
    ) -> VoiceExistenceResult:
        matches: list[str] = []
        visibility_known = False
        page_size = 100
        try:
            with _client() as client:
                # Pagination is intentionally private to this adapter.  Only
                # recovery-name matches leave this method.
                for page in range(10):
                    response = client.post(
                        f"{_base_url(self.config)}{VOICE_CUSTOMIZATION_PATH}",
                        headers={"Authorization": f"Bearer {self.config.api_key}"},
                        json={
                            "model": VOICE_ENROLLMENT_MODEL,
                            "input": {
                                "action": "list",
                                "page_index": page,
                                "page_size": page_size,
                            },
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
                        voice = row.get("voice")
                        if not isinstance(voice, str) or not voice.startswith(recovery_name):
                            continue
                        if row.get("target_model") not in {None, target_model_key}:
                            continue
                        if isinstance(voice, str) and voice and len(voice) <= 512:
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
        payload = {
            "model": VOICE_ENROLLMENT_MODEL,
            "input": {"action": "delete", "voice": external_voice_id},
        }
        del target_model_key
        try:
            with _client() as client:
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


class DashScopeTTSProvider:
    """DashScope non-streaming TTS adapter with bounded result download."""

    key = "dashscope"

    def __init__(
        self, config: DashScopeConfig, downloader: SupplierAudioDownloader | None = None
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
    ) -> TTSResult:
        payload = {
            "model": self.target_model_key,
            "input": {"text": text, "voice": external_voice_id},
        }
        del language
        # Validate region/workspace before constructing a client or crossing
        # the provider boundary.  The reviewed contract selects the Beijing
        # workspace endpoint rather than relying on a shared host/header.
        endpoint = f"{_base_url(self.config)}{TTS_GENERATION_PATH}"
        try:
            with _client() as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
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
        raw = self.downloader.download(audio_url)
        try:
            validate_technical_audio(raw)
        except AudioValidationError as exc:
            raise TTSAudioInvalidError("provider audio invalid") from exc
        return TTSResult(raw, "audio/wav", _request_id(response, document))
