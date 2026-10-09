"""Small, process-local authentication abuse limits for the single-worker app."""

from __future__ import annotations

import ipaddress
import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from threading import RLock
from typing import TypeVar

from fastapi import Request

from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.identity import username_key

_RESERVATION_TTL_SECONDS = 120
_CLEANUP_INTERVAL_SECONDS = 30
_BucketKey = TypeVar("_BucketKey", bound=Hashable)


@dataclass
class _Bucket:
    failures: deque[float] = field(default_factory=deque)
    reservations: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LoginReservation:
    account_key: tuple[str, str]
    client_key: str
    token: int


class AuthAbuseLimiter:
    """Thread-safe sliding-window buckets shared by requests in one process.

    Login reservations make the limit atomic while password verification runs
    outside the lock. A successful verification releases its reservation
    without adding a failure, so successful classroom logins do not spend the
    failed-login allowance.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = RLock()
        self._next_token = 0
        self._last_cleanup = 0.0
        self._account_failures: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()
        self._client_failures: OrderedDict[str, _Bucket] = OrderedDict()
        self._registrations: OrderedDict[str, _Bucket] = OrderedDict()

    def reserve_login(self, client_key: str, username: str, settings: Settings) -> LoginReservation:
        now = self._clock()
        account_key = (client_key, username_key(username))
        with self._lock:
            self._cleanup(now, settings)
            account_bucket_existed = account_key in self._account_failures
            account_bucket = self._get_bucket(
                self._account_failures,
                account_key,
                settings.auth_abuse_max_buckets,
                now,
                settings.auth_login_failure_window_seconds,
            )
            if account_bucket is None:
                raise _rate_limited(
                    self._capacity_retry_after(
                        self._account_failures,
                        now,
                        settings.auth_login_failure_window_seconds,
                    )
                )
            client_bucket_existed = client_key in self._client_failures
            client_bucket = self._get_bucket(
                self._client_failures,
                client_key,
                settings.auth_abuse_max_buckets,
                now,
                settings.auth_login_failure_window_seconds,
            )
            if client_bucket is None:
                if not account_bucket_existed:
                    self._account_failures.pop(account_key, None)
                raise _rate_limited(
                    self._capacity_retry_after(
                        self._client_failures,
                        now,
                        settings.auth_login_failure_window_seconds,
                    )
                )
            retry_after = max(
                self._retry_after(
                    account_bucket,
                    now,
                    settings.auth_login_failure_window_seconds,
                    settings.auth_login_account_failure_limit,
                ),
                self._retry_after(
                    client_bucket,
                    now,
                    settings.auth_login_failure_window_seconds,
                    settings.auth_login_client_failure_limit,
                ),
            )
            if retry_after:
                if not account_bucket_existed and not account_bucket.failures:
                    self._account_failures.pop(account_key, None)
                if not client_bucket_existed and not client_bucket.failures:
                    self._client_failures.pop(client_key, None)
                raise _rate_limited(retry_after)
            self._next_token += 1
            token = self._next_token
            account_bucket.reservations[token] = now
            client_bucket.reservations[token] = now
            self._account_failures.move_to_end(account_key)
            self._client_failures.move_to_end(client_key)
            return LoginReservation(account_key, client_key, token)

    def finish_login(self, reservation: LoginReservation, *, failed: bool) -> None:
        now = self._clock()
        with self._lock:
            account_bucket = self._account_failures.get(reservation.account_key)
            client_bucket = self._client_failures.get(reservation.client_key)
            if account_bucket is not None:
                account_bucket.reservations.pop(reservation.token, None)
                if failed:
                    account_bucket.failures.append(now)
                self._account_failures.move_to_end(reservation.account_key)
            if client_bucket is not None:
                client_bucket.reservations.pop(reservation.token, None)
                if failed:
                    client_bucket.failures.append(now)
                self._client_failures.move_to_end(reservation.client_key)

    def consume_registration(self, client_key: str, settings: Settings) -> None:
        now = self._clock()
        with self._lock:
            self._cleanup(now, settings)
            bucket = self._get_bucket(
                self._registrations,
                client_key,
                settings.auth_abuse_max_buckets,
                now,
                settings.auth_register_window_seconds,
            )
            if bucket is None:
                raise _rate_limited(
                    self._capacity_retry_after(
                        self._registrations,
                        now,
                        settings.auth_register_window_seconds,
                    )
                )
            retry_after = self._retry_after(
                bucket,
                now,
                settings.auth_register_window_seconds,
                settings.auth_register_client_limit,
            )
            if retry_after:
                raise _rate_limited(retry_after)
            bucket.failures.append(now)
            self._registrations.move_to_end(client_key)

    def bucket_count(self) -> int:
        """Expose bounded storage to focused tests without exposing account keys."""

        with self._lock:
            return (
                len(self._account_failures) + len(self._client_failures) + len(self._registrations)
            )

    def _cleanup(self, now: float, settings: Settings) -> None:
        if now - self._last_cleanup < _CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = now
        self._expire_map(
            self._account_failures,
            now,
            settings.auth_login_failure_window_seconds,
        )
        self._expire_map(
            self._client_failures,
            now,
            settings.auth_login_failure_window_seconds,
        )
        self._expire_map(
            self._registrations,
            now,
            settings.auth_register_window_seconds,
        )

    @staticmethod
    def _expire_map(
        buckets: OrderedDict[_BucketKey, _Bucket], now: float, window_seconds: int
    ) -> None:
        expired: list[_BucketKey] = []
        for key, bucket in buckets.items():
            while bucket.failures and bucket.failures[0] <= now - window_seconds:
                bucket.failures.popleft()
            for token, reserved_at in tuple(bucket.reservations.items()):
                if reserved_at <= now - _RESERVATION_TTL_SECONDS:
                    del bucket.reservations[token]
            if not bucket.failures and not bucket.reservations:
                expired.append(key)
        for key in expired:
            del buckets[key]

    @staticmethod
    def _get_bucket(
        buckets: OrderedDict[_BucketKey, _Bucket],
        key: _BucketKey,
        max_buckets: int,
        now: float,
        window_seconds: int,
    ) -> _Bucket | None:
        bucket = buckets.get(key)
        if bucket is not None:
            buckets.move_to_end(key)
            return bucket
        if len(buckets) >= max_buckets:
            AuthAbuseLimiter._expire_map(buckets, now, window_seconds)
        if len(buckets) >= max_buckets:
            return None
        bucket = _Bucket()
        buckets[key] = bucket
        return bucket

    @staticmethod
    def _capacity_retry_after(
        buckets: OrderedDict[_BucketKey, _Bucket], now: float, window_seconds: int
    ) -> int:
        """Wait until one complete live bucket expires before retrying a new key."""

        earliest_release: float | None = None
        for bucket in buckets.values():
            bucket_release = now
            if bucket.failures:
                bucket_release = max(bucket_release, bucket.failures[-1] + window_seconds)
            if bucket.reservations:
                bucket_release = max(
                    bucket_release,
                    max(bucket.reservations.values()) + _RESERVATION_TTL_SECONDS,
                )
            if earliest_release is None or bucket_release < earliest_release:
                earliest_release = bucket_release
        if earliest_release is None:
            return 1
        return max(1, math.ceil(earliest_release - now))

    @staticmethod
    def _retry_after(
        bucket: _Bucket,
        now: float,
        window_seconds: int,
        limit: int,
    ) -> int:
        while bucket.failures and bucket.failures[0] <= now - window_seconds:
            bucket.failures.popleft()
        for token, reserved_at in tuple(bucket.reservations.items()):
            if reserved_at <= now - _RESERVATION_TTL_SECONDS:
                del bucket.reservations[token]
        if len(bucket.failures) + len(bucket.reservations) < limit:
            return 0
        if not bucket.failures:
            return 1
        return max(1, math.ceil(bucket.failures[0] + window_seconds - now))


def client_key(request: Request, settings: Settings) -> str:
    """Use Caddy's single overwritten client address only when explicitly trusted."""

    client = request.client.host if request.client is not None else "unknown"
    candidate = client
    if settings.auth_trust_gateway_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        # The production Caddyfile replaces the field with its one TCP peer.
        # Reject comma-separated chains instead of guessing which hop to trust.
        if forwarded and "," not in forwarded:
            candidate = forwarded.strip()
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return f"peer:{candidate.casefold()[:128]}"
    return f"ip:{parsed.compressed}"


def _rate_limited(retry_after_seconds: int) -> PlatformError:
    retry_after = max(1, retry_after_seconds)
    unit = "second" if retry_after == 1 else "seconds"
    return PlatformError(
        "auth_rate_limited",
        f"Too many authentication attempts. Try again in {retry_after} {unit}.",
        429,
        {"retry_after_seconds": retry_after},
    )
