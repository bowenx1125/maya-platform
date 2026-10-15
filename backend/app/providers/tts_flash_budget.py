"""Durable character budget for the qwen3-tts-flash trial path.

Pre-claims characters atomically before any outbound TTS request. Retries and
failed attempts still count. The counter survives process restart under the
deployment data root.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.providers.tts import TTSProviderUnavailableError

TTS_FLASH_TRIAL_BUDGET_CHARS = 20_000
_LEDGER_NAME = "tts_qwen3_flash_trial_chars"


class FlashTrialBudget:
    """File-backed cumulative character ledger with exclusive pre-claim."""

    def __init__(
        self,
        path: Path,
        *,
        cap: int = TTS_FLASH_TRIAL_BUDGET_CHARS,
    ) -> None:
        if cap < 0:
            raise ValueError("trial budget cap is invalid")
        self.path = path
        self.cap = cap

    @classmethod
    def under_data_root(cls, data_root: Path) -> FlashTrialBudget:
        return cls(data_root / "provider" / _LEDGER_NAME)

    def used(self) -> int:
        """Read the durable total without reserving."""

        if not self.path.exists():
            return 0
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise TTSProviderUnavailableError("tts trial budget unavailable") from exc
        if not raw:
            return 0
        try:
            value = int(raw)
        except ValueError as exc:
            raise TTSProviderUnavailableError("tts trial budget unavailable") from exc
        if value < 0:
            raise TTSProviderUnavailableError("tts trial budget unavailable")
        return value

    def preclaim(self, characters: int) -> int:
        """Atomically reserve ``characters`` or refuse before any network I/O.

        Returns the new cumulative total. A refused claim leaves the ledger
        unchanged so a follow-up call can see the same remaining room.
        """

        if not isinstance(characters, int) or isinstance(characters, bool) or characters < 0:
            raise TTSProviderUnavailableError("tts trial budget unavailable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Open+create under exclusive lock so concurrent synthesizes serialize.
        with open(self.path, "a+b") as handle:
            self._lock_exclusive(handle)
            try:
                handle.seek(0)
                raw = handle.read().decode("utf-8").strip()
                current = int(raw) if raw else 0
                if current < 0:
                    raise TTSProviderUnavailableError("tts trial budget unavailable")
                if characters > self.cap or current > self.cap - characters:
                    raise TTSProviderUnavailableError("tts trial budget exhausted")
                updated = current + characters
                payload = f"{updated}\n".encode()
                handle.seek(0)
                handle.truncate()
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                return updated
            finally:
                self._unlock(handle)

    @staticmethod
    def _lock_exclusive(handle: object) -> None:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]

    @staticmethod
    def _unlock(handle: object) -> None:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


__all__ = [
    "FlashTrialBudget",
    "TTS_FLASH_TRIAL_BUDGET_CHARS",
]
