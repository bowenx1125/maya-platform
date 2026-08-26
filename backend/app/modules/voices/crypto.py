"""Versioned AES-GCM envelope for server-only external voice mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VOICE_ENVELOPE_VERSION: Final[int] = 1
VOICE_NONCE_BYTES: Final[int] = 12
VOICE_KEY_BYTES: Final[int] = 32
VOICE_MAPPING_PURPOSE: Final[bytes] = b"maya/platform/voice-mapping/aes-gcm/v1"


class VoiceEncryptionError(ValueError):
    """Raised when a voice envelope cannot be safely encrypted/decrypted."""


@dataclass(frozen=True)
class VoiceEnvelope:
    """An in-memory parsed envelope; never serialised to an API DTO."""

    version: int
    nonce: bytes
    ciphertext_and_tag: bytes

    def encode(self) -> bytes:
        if self.version != VOICE_ENVELOPE_VERSION or len(self.nonce) != VOICE_NONCE_BYTES:
            raise VoiceEncryptionError("invalid voice envelope")
        if len(self.ciphertext_and_tag) < 16:
            raise VoiceEncryptionError("invalid voice envelope")
        return bytes([self.version]) + self.nonce + self.ciphertext_and_tag

    @classmethod
    def decode(cls, value: bytes) -> VoiceEnvelope:
        if (
            not isinstance(value, bytes)
            or len(value) < 1 + VOICE_NONCE_BYTES + 16
            or value[0] != VOICE_ENVELOPE_VERSION
        ):
            raise VoiceEncryptionError("invalid voice envelope")
        return cls(value[0], value[1 : 1 + VOICE_NONCE_BYTES], value[1 + VOICE_NONCE_BYTES :])


def derive_voice_mapping_key(server_secret: bytes | str) -> bytes:
    """Derive a purpose-separated 256-bit mapping key from the server secret."""

    secret = server_secret.encode("utf-8") if isinstance(server_secret, str) else server_secret
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise VoiceEncryptionError("voice mapping key is not configured")
    try:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=VOICE_KEY_BYTES,
            salt=None,
            info=VOICE_MAPPING_PURPOSE,
        ).derive(secret)
    except Exception as exc:  # pragma: no cover - backend crypto failure
        raise VoiceEncryptionError("voice mapping key is not configured") from exc


def envelope_aad(
    profile_id: str,
    scope: str,
    group_id: str | None,
    provider_key: str,
    target_model_key: str,
) -> bytes:
    """Bind a ciphertext to its exact profile/scope/provider row."""

    values = (profile_id, scope, group_id or "", provider_key, target_model_key)
    if any(not isinstance(value, str) for value in values):
        raise VoiceEncryptionError("invalid voice envelope context")
    # Length prefixes avoid ambiguity from a separator appearing in metadata.
    return b"|".join(
        str(len(value)).encode("ascii") + b":" + value.encode("utf-8") for value in values
    )


def encrypt_external_voice_id(
    external_voice_id: str,
    server_secret: bytes | str,
    *,
    profile_id: str,
    scope: str,
    group_id: str | None,
    provider_key: str,
    target_model_key: str,
) -> bytes:
    """Encrypt one supplier identifier with fresh nonce and row-bound AAD."""

    if not external_voice_id or not isinstance(external_voice_id, str):
        raise VoiceEncryptionError("invalid voice mapping")
    key = derive_voice_mapping_key(server_secret)
    # AESGCM needs a random 96-bit nonce.  ``secrets.token_bytes`` keeps this
    # independent from any provider identifier and guarantees per-call fresh
    # nonce material.
    import secrets

    nonce = secrets.token_bytes(VOICE_NONCE_BYTES)
    aad = envelope_aad(profile_id, scope, group_id, provider_key, target_model_key)
    ciphertext = AESGCM(key).encrypt(nonce, external_voice_id.encode("utf-8"), aad)
    return VoiceEnvelope(VOICE_ENVELOPE_VERSION, nonce, ciphertext).encode()


def decrypt_external_voice_id(
    envelope_bytes: bytes,
    server_secret: bytes | str,
    *,
    profile_id: str,
    scope: str,
    group_id: str | None,
    provider_key: str,
    target_model_key: str,
) -> str:
    """Decrypt a row-bound mapping or raise one safe internal error."""

    try:
        envelope = VoiceEnvelope.decode(envelope_bytes)
        key = derive_voice_mapping_key(server_secret)
        aad = envelope_aad(profile_id, scope, group_id, provider_key, target_model_key)
        value = AESGCM(key).decrypt(envelope.nonce, envelope.ciphertext_and_tag, aad)
        decoded = value.decode("utf-8")
    except (VoiceEncryptionError, InvalidTag, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise VoiceEncryptionError("voice mapping unavailable") from exc
    if not decoded:
        raise VoiceEncryptionError("voice mapping unavailable")
    return decoded
