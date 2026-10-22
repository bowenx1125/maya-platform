#!/usr/bin/env python3
"""Exercise same-name invalid/valid imports over real HTTP on an isolated stack.

Pass a private JSON file containing base_url and accounts with username,
password, course_id and group_id. Accounts may share an isolated test group.
Only loopback or the isolated Compose gateway is accepted. Eight synchronized
waves send exactly 8 * account-count import requests, without automatic retries.
The isolated database and account file must be discarded after the run.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from load_tune import Client, HttpResult, percentile

VALID_CONTENT = b"# Replacement\nvalid content"


def payload(result: HttpResult) -> dict[str, Any]:
    try:
        value = json.loads(result.body)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def upload(
    client: Client, path: str, fields: dict[str, str], filename: str, content: bytes
) -> HttpResult:
    boundary = f"maya-load-{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    parts.extend(
        [
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\nContent-Type: text/markdown\r\n\r\n'
            ).encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    request = urllib.request.Request(
        client.base + path, data=b"".join(parts), method="POST"
    )
    request.add_header("Origin", client.base)
    request.add_header("X-CSRF-Token", client.csrf)
    request.add_header("Idempotency-Key", f"upload-load-{uuid.uuid4()}")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with client.opener.open(request, timeout=client.timeout) as response:
            return HttpResult(
                response.status, response.read().decode("utf-8", "replace")
            )
    except urllib.error.HTTPError as error:
        result = HttpResult(error.code, error.read().decode("utf-8", "replace"))
        result.code = payload(result).get("code")
        return result
    except (urllib.error.URLError, TimeoutError, OSError):
        return HttpResult(599, "", "transport_error")


@dataclass
class Actor:
    index: int
    client: Client
    group_id: str
    version_id: str
    original: dict[str, Any]
    run_id: str
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def filename(self, scope: str) -> str:
        return f"{self.run_id}-{self.index:03d}-{scope}-lesson.md"

    def endpoint(self, scope: str) -> tuple[str, dict[str, str]]:
        if scope == "replace":
            return (
                f"/api/v1/knowledge-documents/{self.original['id']}/replace",
                {
                    "expected_content_hash": self.original["content_hash"],
                    "expected_index_revision": str(self.original["index_revision"]),
                },
            )
        fields = {"visibility": "public" if scope == "public" else "private"}
        if scope == "agent":
            fields.update(
                target_agent_version_id=self.version_id, expected_revision="0"
            )
        return f"/api/v1/groups/{self.group_id}/knowledge-documents", fields


def prepare(
    index: int, account: dict[str, str], base_url: str, timeout: float, run_id: str
) -> Actor:
    client = Client(base_url, timeout)
    client.opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    signed_in = client.call(
        "POST",
        "/api/v1/auth/login",
        {"username": account["username"], "password": account["password"]},
    )
    session = payload(signed_in)
    client.csrf = str(session.get("csrf_token") or "")
    if signed_in.status != 200 or not client.csrf:
        raise ValueError(f"participant {index}: login HTTP {signed_in.status}")
    user = session.get("user", {})
    if user.get("username") != account["username"] or (
        account.get("user_id") is not None and user.get("id") != account["user_id"]
    ):
        raise ValueError(f"participant {index}: login identity mismatch")
    group_id = account["group_id"]
    groups = session.get("user", {}).get("groups", [])
    if not any(group.get("group_id") == group_id for group in groups):
        raise ValueError(f"participant {index}: assigned group absent from session")
    created = client.call(
        "POST",
        f"/api/v1/groups/{group_id}/agents",
        {"name": f"Upload {run_id} {index}", "visibility": "private"},
        Idempotency_Key=f"upload-agent-{uuid.uuid4()}",
    )
    versions = payload(created).get("versions", [])
    if created.status != 201 or not versions or versions[0].get("revision") != 0:
        raise ValueError(f"participant {index}: create Agent HTTP {created.status}")
    actor = Actor(index, client, group_id, versions[0]["id"], {}, run_id)
    original = upload(
        client,
        f"/api/v1/groups/{group_id}/knowledge-documents",
        {"visibility": "private"},
        actor.filename("replace"),
        b"# Original\nvalid content",
    )
    actor.original = payload(original).get("document", {})
    if original.status != 201 or not all(
        key in actor.original for key in ("id", "content_hash", "index_revision")
    ):
        raise ValueError(
            f"participant {index}: prepare replacement HTTP {original.status}"
        )
    return actor


def validate(actor: Actor, scope: str, valid: bool, result: HttpResult) -> str | None:
    body = payload(result)
    if not valid:
        if result.status != 422:
            return f"invalid_http_{result.status}"
        if body.get("code") != "knowledge_import_invalid":
            return "invalid_error_code"
        if body.get("details", {}).get("reason") != "invalid_control_chars":
            return "invalid_error_reason"
        return None
    if result.status != 201:
        return f"corrected_http_{result.status}"
    document = body if scope == "replace" else body.get("document", {})
    if document.get("source_filename") != actor.filename(scope):
        return "corrected_filename_mismatch"
    if document.get("index_status") != "ready":
        return "corrected_index_not_ready"
    if (
        document.get("content_hash") != hashlib.sha256(VALID_CONTENT).hexdigest()
        or document.get("char_count") != len(VALID_CONTENT)
        or document.get("group_id") != actor.group_id
        or document.get("visibility") != ("public" if scope == "public" else "private")
    ):
        return "corrected_content_or_scope_mismatch"
    if scope == "replace" and (
        document.get("id") != actor.original["id"]
        or document.get("content_hash") == actor.original["content_hash"]
        or document.get("index_revision") != actor.original["index_revision"] + 1
    ):
        return "corrected_replace_state_mismatch"
    if scope == "agent" and body.get("agent_version", {}).get("revision") != 1:
        return "corrected_agent_revision_mismatch"
    actor.documents[scope] = document
    return None


def run_wave(actors: list[Actor], scope: str, valid: bool) -> dict[str, Any]:
    barrier = threading.Barrier(len(actors))
    lock = threading.Lock()
    active = peak = 0
    starts: list[float] = []
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []
    statuses: Counter[int] = Counter()
    codes: Counter[str] = Counter()

    def participant(actor: Actor) -> None:
        nonlocal active, peak
        path, fields = actor.endpoint(scope)
        content = VALID_CONTENT if valid else b"# Lesson\ninvalid\x00content"
        barrier.wait(timeout=30)
        started = time.perf_counter()
        with lock:
            starts.append(started)
            active += 1
            peak = max(peak, active)
        try:
            result = upload(actor.client, path, fields, actor.filename(scope), content)
            failure = validate(actor, scope, valid, result)
        finally:
            with lock:
                active -= 1
        elapsed = (time.perf_counter() - started) * 1000
        with lock:
            latencies.append(elapsed)
            statuses[result.status] += 1
            if result.code:
                codes[result.code] += 1
            if failure:
                failures.append({"participant": actor.index, "reason": failure})

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(actors)) as pool:
        list(pool.map(participant, actors))
    summary = {
        "wave": f"{scope}_{'corrected' if valid else 'invalid'}",
        "requests": len(actors),
        "passed": len(actors) - len(failures),
        "failed": len(failures),
        "http_statuses": dict(statuses),
        "error_codes": dict(codes),
        "peak_client_in_flight": peak,
        "launch_spread_ms": round((max(starts) - min(starts)) * 1000, 3),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "p50_ms": round(percentile(latencies, 0.5) or 0, 3),
        "p95_ms": round(percentile(latencies, 0.95) or 0, 3),
        "max_ms": round(max(latencies), 3),
        "failures": sorted(failures, key=lambda value: value["participant"]),
    }
    print(json.dumps(summary), flush=True)
    return summary


def check_original(actor: Actor) -> bool:
    result = actor.client.call(
        "GET", f"/api/v1/knowledge-documents/{actor.original['id']}"
    )
    current = payload(result)
    return result.status == 200 and all(
        current.get(key) == actor.original[key]
        for key in ("id", "content_hash", "index_revision")
    )


def check_persisted(actor: Actor, scope: str) -> bool:
    original = actor.documents.get(scope)
    if not original:
        return False
    result = actor.client.call("GET", f"/api/v1/knowledge-documents/{original['id']}")
    current = payload(result)
    return (
        result.status == 200
        and current.get("can_manage_visibility") is True
        and all(
            current.get(key) == original.get(key)
            for key in (
                "id",
                "content_hash",
                "index_revision",
                "source_filename",
                "group_id",
                "visibility",
                "char_count",
                "index_status",
            )
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-file", required=True, type=Path)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=210)
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 50 or args.timeout <= 0:
        parser.error("count must be 1..50 and timeout must be positive")
    manifest = json.loads(args.account_file.read_text(encoding="utf-8"))
    base_url = str(manifest["base_url"]).rstrip("/")
    address = urllib.parse.urlsplit(base_url)
    if (
        address.scheme != "http"
        or address.hostname
        not in {"gateway", "gateway.local", "localhost", "127.0.0.1", "::1"}
        or address.username
        or address.password
        or address.path
        or address.query
        or address.fragment
    ):
        parser.error("only the isolated HTTP gateway or loopback is allowed")
    accounts = manifest["accounts"][: args.count]
    if (
        len(accounts) != args.count
        or len({account["username"] for account in accounts}) != args.count
    ):
        parser.error("provide the requested number of distinct accounts")
    run_id = uuid.uuid4().hex[:12]
    actors: list[Actor] = []
    try:
        with ThreadPoolExecutor(max_workers=min(8, args.count)) as pool:
            actors = list(
                pool.map(
                    lambda item: prepare(
                        item[0], item[1], base_url, args.timeout, run_id
                    ),
                    enumerate(accounts),
                )
            )
        print(json.dumps({"stage": "prepared", "accounts": len(actors)}), flush=True)
        waves = []
        unchanged = args.count
        persisted = 0
        for scope in ("agent", "private", "public", "replace"):
            waves.append(run_wave(actors, scope, False))
            if scope == "replace":
                with ThreadPoolExecutor(max_workers=args.count) as pool:
                    unchanged = sum(pool.map(check_original, actors))
                print(
                    json.dumps(
                        {"stage": "invalid_replace_unchanged", "passed": unchanged}
                    ),
                    flush=True,
                )
            waves.append(run_wave(actors, scope, True))
            with ThreadPoolExecutor(max_workers=args.count) as pool:
                checked = sum(
                    pool.map(
                        lambda actor, current=scope: check_persisted(actor, current),
                        actors,
                    )
                )
            persisted += checked
            print(
                json.dumps({"stage": f"{scope}_persisted_owned", "passed": checked}),
                flush=True,
            )
        passed = (
            unchanged == args.count
            and persisted == args.count * 4
            and all(wave["failed"] == 0 for wave in waves)
        )
        print(
            json.dumps(
                {
                    "stage": "result",
                    "passed": passed,
                    "accounts": len(actors),
                    "upload_requests": sum(wave["requests"] for wave in waves),
                    "same_name_pairs": args.count * 4,
                    "automatic_retries": 0,
                    "replacement_unchanged_after_invalid": unchanged,
                    "persisted_owned_documents": persisted,
                }
            ),
            flush=True,
        )
        return 0 if passed else 1
    except ValueError as error:
        print(json.dumps({"stage": "setup_failed", "reason": str(error)}), flush=True)
        return 1
    finally:
        with ThreadPoolExecutor(max_workers=min(8, args.count)) as pool:
            list(
                pool.map(
                    lambda actor: actor.client.call("POST", "/api/v1/auth/logout"),
                    actors,
                )
            )


if __name__ == "__main__":
    sys.exit(main())
