#!/usr/bin/env python3
"""Exercise real HTTP login/hash/session handling against an isolated mock stack.

The account file contains credentials. Keep it outside the repository, mount it
only into the isolated load clients, and remove it with that stack after the run.
No provider endpoints are called and failed operations are never retried.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import http.cookiejar
import json
import math
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class Client:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        cookie: str | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Origin": self.base_url}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if cookie is not None:
            headers["Cookie"] = "maya_session=" + cookie
        request = urllib.request.Request(
            self.base_url + path, data, headers, method=method
        )
        started = time.perf_counter()
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return {
                "status": 599,
                "code": type(error).__name__,
                "payload": {},
                "ms": (time.perf_counter() - started) * 1000,
            }
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        error_payload = payload.get("error", payload)
        code = error_payload.get("code") if isinstance(error_payload, dict) else None
        return {
            "status": status,
            "code": code,
            "payload": payload,
            "ms": (time.perf_counter() - started) * 1000,
        }

    def session_cookie(self) -> str:
        return next(
            (cookie.value for cookie in self.jar if cookie.name == "maya_session"), ""
        )


def stats(values: list[float]) -> dict[str, int | float | None]:
    values = sorted(values)

    def percentile(fraction: float) -> float | None:
        return (
            round(values[max(0, math.ceil(len(values) * fraction) - 1)], 2)
            if values
            else None
        )

    return {
        "count": len(values),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "max_ms": round(max(values), 2) if values else None,
    }


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **stats([item["ms"] for item in results]),
        "statuses": dict(collections.Counter(str(item["status"]) for item in results)),
        "failure_codes": dict(
            collections.Counter(
                str(item["code"] or item["status"])
                for item in results
                if item["status"] != 200
            )
        ),
    }


class HealthSampler(threading.Thread):
    def __init__(self, base_url: str) -> None:
        super().__init__(daemon=True)
        self.client = Client(base_url, 10)
        self.done = threading.Event()
        self.results: list[dict[str, Any]] = []

    def run(self) -> None:
        while not self.done.is_set():
            self.results.append(self.client.call("GET", "/health/ready"))
            self.done.wait(0.1)


def identity_ok(response: dict[str, Any], account: dict[str, str]) -> bool:
    user = response["payload"].get("user", {})
    return (
        response["status"] == 200
        and user.get("username") == account["username"]
        and user.get("id") == account["user_id"]
    )


def login_wave(
    clients: list[Client],
    accounts: list[dict[str, str]],
    label: str,
) -> tuple[dict[str, Any], bool]:
    barrier = threading.Barrier(len(accounts) + 1)
    starts: list[float] = []
    sampler = HealthSampler(clients[0].base_url)

    def login(pair: tuple[Client, dict[str, str]]) -> dict[str, Any]:
        client, account = pair
        barrier.wait(timeout=30)
        starts.append(time.perf_counter())
        return client.call(
            "POST",
            "/api/v1/auth/login",
            {
                "username": account["username"],
                "password": account["password"],
            },
        )

    sampler.start()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(accounts)) as pool:
        futures = [
            pool.submit(login, pair) for pair in zip(clients, accounts, strict=True)
        ]
        barrier.wait(timeout=30)
        results = [future.result() for future in futures]
    elapsed = time.perf_counter() - started
    sampler.done.set()
    sampler.join(timeout=12)
    identities = sum(
        identity_ok(result, account)
        for result, account in zip(results, accounts, strict=True)
    )
    cookies = [client.session_cookie() for client in clients]
    unique = len(set(cookies)) == len(accounts) and all(cookies)
    value = {
        "phase": label,
        **summary(results),
        "wall_seconds": round(elapsed, 3),
        "dispatch_spread_ms": round((max(starts) - min(starts)) * 1000, 2),
        "identities_correct": identities,
        "unique_session_cookies": bool(unique),
        "health_ready": summary(sampler.results),
    }
    print(json.dumps(value), flush=True)
    return value, (
        identities == len(accounts)
        and bool(unique)
        and all(result["status"] == 200 for result in sampler.results)
    )


def check_sessions(
    clients: list[Client],
    accounts: list[dict[str, str]],
    old_cookies: list[str] | None = None,
) -> dict[str, Any]:
    def check(pair: tuple[Client, dict[str, str], str | None]) -> tuple[bool, bool]:
        client, account, old_cookie = pair
        current = identity_ok(client.call("GET", "/api/v1/auth/me"), account)
        old_revoked = True
        if old_cookie is not None:
            old = Client(client.base_url, client.timeout).call(
                "GET",
                "/api/v1/auth/me",
                cookie=old_cookie,
            )
            old_revoked = old["status"] == 401
        return current, old_revoked

    previous = old_cookies or [None] * len(accounts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        checked = list(pool.map(check, zip(clients, accounts, previous, strict=True)))
    return {
        "current_identity_correct": sum(item[0] for item in checked),
        "old_session_revoked": sum(item[1] for item in checked)
        if old_cookies
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://gateway:8080")
    parser.add_argument("--account-file", type=Path, required=True)
    parser.add_argument("--accounts", type=int, default=50)
    parser.add_argument("--register-workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--course-id", default="")
    parser.add_argument("--group-name", default="Isolated Fifty Load")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    url = urllib.parse.urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname not in {
        "gateway",
        "gateway.local",
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        parser.error("Only isolated gateway or loopback HTTP targets are allowed")
    if not 1 <= args.accounts <= 100 or not 1 <= args.register_workers <= 8:
        parser.error("Use 1..100 accounts and 1..8 registration workers")
    if args.account_file.exists():
        parser.error("Refusing to overwrite an existing credential file")
    prefix = "load" + time.strftime("%Y%m%d%H%M%S", time.gmtime()) + secrets.token_hex(2)
    accounts = [
        {"username": f"{prefix}{index:03d}", "password": secrets.token_urlsafe(24)}
        for index in range(args.accounts)
    ]
    registration_results: list[dict[str, Any]] = []

    def register(account: dict[str, str]) -> dict[str, str]:
        body = {**account, "group_name": args.group_name}
        if args.course_id:
            body["course_id"] = args.course_id
        response = Client(args.base_url, args.timeout).call(
            "POST", "/api/v1/auth/register", body
        )
        registration_results.append(response)
        if response["status"] != 201:
            raise RuntimeError(
                f"Registration failed: HTTP {response['status']} {response['code']}"
            )
        user = response["payload"].get("user", {})
        return {
            **account,
            "user_id": user["id"],
            "course_id": user["courses"][0]["course_id"],
            "group_id": user["groups"][0]["group_id"],
        }

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.register_workers
    ) as pool:
        accounts = list(pool.map(register, accounts))
    if len({account["group_id"] for account in accounts}) != 1:
        raise RuntimeError("Registered accounts do not share one isolated test group")
    args.account_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.account_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump({"base_url": args.base_url, "accounts": accounts}, output)
    os.chmod(args.account_file, 0o600)
    print(
        json.dumps(
            {
                "phase": "registered",
                "count": len(accounts),
                "wall_seconds": round(time.perf_counter() - started, 3),
                **stats([item["ms"] for item in registration_results]),
            }
        ),
        flush=True,
    )
    clients = [Client(args.base_url, args.timeout) for _ in accounts]
    _, first_ok = login_wave(clients, accounts, "login_wave_1")
    first_sessions = check_sessions(clients, accounts)
    print(json.dumps({"phase": "sessions_wave_1", **first_sessions}), flush=True)
    old_cookies = [client.session_cookie() for client in clients]
    _, second_ok = login_wave(clients, accounts, "login_wave_2_same_browser")
    second_sessions = check_sessions(clients, accounts, old_cookies)
    changed = sum(
        client.session_cookie() != previous
        for client, previous in zip(clients, old_cookies, strict=True)
    )
    independent = Client(args.base_url, args.timeout)
    account = accounts[0]
    other_login = independent.call(
        "POST",
        "/api/v1/auth/login",
        {
            "username": account["username"],
            "password": account["password"],
        },
    )
    independent_ok = (
        identity_ok(other_login, account)
        and identity_ok(independent.call("GET", "/api/v1/auth/me"), account)
        and identity_ok(clients[0].call("GET", "/api/v1/auth/me"), account)
        and independent.session_cookie() != clients[0].session_cookie()
    )
    passed = (
        first_ok
        and second_ok
        and first_sessions["current_identity_correct"] == args.accounts
        and second_sessions["current_identity_correct"] == args.accounts
        and second_sessions["old_session_revoked"] == args.accounts
        and changed == args.accounts
        and independent_ok
    )
    print(
        json.dumps(
            {
                "phase": "session_validation",
                **second_sessions,
                "rotated_cookies": changed,
                "independent_session_preserved": independent_ok,
                "passed": passed,
            }
        ),
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
