#!/usr/bin/env python3
"""Exercise isolated Mock Chat over HTTP, including 50-way SSE and send races.

Account input is a private JSON file produced by load_auth_http.py. Use only a
throwaway database and a network with no external Provider access. This measures
HTTP/DB/SSE overhead, not real model latency or production classroom capacity.
"""

from __future__ import annotations

import argparse
import copy
import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from load_tune import Client, parse_sse, percentile


def decoded(result: Any, statuses: tuple[int, ...] = (200,)) -> Any:
    if result.status not in statuses:
        raise RuntimeError(
            f"HTTP {result.status}: {result.code or 'unexpected_status'}"
        )
    return json.loads(result.body)


def new_client(base: str, timeout: float) -> Client:
    client = Client(base, timeout)
    client.opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )
    return client


def clone(client: Client) -> Client:
    other = new_client(client.base, client.timeout)
    source = next(
        h.cookiejar for h in client.opener.handlers if hasattr(h, "cookiejar")
    )
    target = next(h.cookiejar for h in other.opener.handlers if hasattr(h, "cookiejar"))
    for cookie in source:
        target.set_cookie(copy.copy(cookie))
    other.csrf = client.csrf
    return other


def stream(client: Client, conversation: str, body: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {"status": 599, "terminal": None, "code": None}
    try:
        path = f"/api/v1/conversations/{conversation}/messages:stream"
        with client._request(
            "POST", path, body, Accept="text/event-stream"
        ) as response:
            result["status"] = response.status
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                result["code"] = "not_event_stream"
            else:
                lines = (line.decode("utf-8") for line in response)
                for event, data in parse_sse(lines):
                    result.setdefault(
                        "first_event_ms", (time.perf_counter() - started) * 1000
                    )
                    payload = json.loads(data)
                    if event in {
                        "text_done",
                        "turn_done",
                        "pending",
                        "error",
                        "turn_failed",
                    }:
                        result["terminal"] = event
                        result["terminal_state"] = payload.get("state")
                        result["code"] = payload.get("safe_error_code") or payload.get(
                            "code"
                        )
                        if payload.get("request_id") != body["request_id"]:
                            result["code"] = "response_request_mismatch"
                        elif event == "text_done" and not payload.get("assistant_text"):
                            result["code"] = "empty_assistant_text"
                        elif event == "turn_done" and payload.get("state") != "ready":
                            result["code"] = "turn_not_ready"
                        if event in {"error", "turn_failed"}:
                            result["code"] = result["code"] or event
                        break
                if result["terminal"] is None and result["code"] is None:
                    result["code"] = "stream_ended_without_completion"
    except urllib.error.HTTPError as error:
        result["status"] = error.code
        try:
            result["code"] = json.loads(error.read()).get("code", "http_error")
        except (ValueError, AttributeError):
            result["code"] = "http_error"
    except (OSError, ValueError, urllib.error.URLError):
        result["code"] = "transport_or_stream_error"
    result["started_at"] = started
    result["finished_at"] = time.perf_counter()
    result["elapsed_ms"] = (result["finished_at"] - started) * 1000
    return result


def parallel_send(
    jobs: list[tuple[Client, str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    barrier = threading.Barrier(len(jobs))

    def send(job: tuple[Client, str, dict[str, Any]]) -> dict[str, Any]:
        barrier.wait(timeout=120)
        return stream(*job)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        return list(pool.map(send, jobs))


def is_done(result: dict[str, Any]) -> bool:
    return (
        result["status"] == 200
        and result["terminal"] in {"text_done", "turn_done"}
        and not result["code"]
    )


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [r["elapsed_ms"] for r in results]
    starts = [r["started_at"] for r in results]
    active = peak = 0
    events = [(r["started_at"], 1) for r in results] + [
        (r["finished_at"], -1) for r in results
    ]
    for _, change in sorted(events):
        active += change
        peak = max(peak, active)
    return {
        "launch_spread_ms": (max(starts) - min(starts)) * 1000,
        "peak_client_in_flight": peak,
        "requests": len(results),
        "completed": sum(is_done(r) for r in results),
        "statuses": dict(Counter(str(r["status"]) for r in results)),
        "terminals": dict(Counter(str(r["terminal"]) for r in results)),
        "terminal_states": dict(Counter(str(r.get("terminal_state")) for r in results)),
        "errors": dict(Counter(r["code"] for r in results if r["code"])),
        "latency_ms": {
            "p50": percentile(elapsed, 0.5),
            "p95": percentile(elapsed, 0.95),
            "max": max(elapsed),
        },
    }


def snapshot(client: Client, conversation: str) -> dict[str, Any]:
    return decoded(client.call("GET", f"/api/v1/conversations/{conversation}"))


def check_turn(view: dict[str, Any], request_id: str, count: int) -> bool:
    turns = view.get("turns", [])
    matches = [turn for turn in turns if turn["id"] == request_id]
    if len(turns) != count or len(matches) != 1 or view["revision"] != count:
        return False
    turn = matches[0]
    if view.get("entry_kind") == "agent":
        return (
            turn["state"] == "ready"
            and turn["mode"] == "mock"
            and bool(turn["assistant_text"])
        )
    members = {member["id"] for member in view["team"]["members"]}
    results = turn.get("member_results", [])
    return (
        turn["state"] == "ready"
        and turn["mode"] == "mock"
        and len(members) == 2
        and len(results) == 2
        and {item["participant_id"] for item in results} == members
        and all(
            item["state"] == "ready" and bool(item["assistant_text"])
            for item in results
        )
    )


def body(revision: int, text: str, team: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {
        "request_id": str(uuid.uuid4()),
        "expected_revision": revision,
        "message": text,
    }
    if team:
        value["routing"] = {"mode": "all", "participant_ids": []}
    return value


def run_phase(
    clients: list[Client], conversations: list[str], team: bool
) -> dict[str, Any]:
    payloads = [
        body(0, f"Synthetic concurrency check {i}", team) for i in range(len(clients))
    ]
    results = parallel_send(list(zip(clients, conversations, payloads)))
    views = [
        snapshot(client, conversation)
        for client, conversation in zip(clients, conversations)
    ]
    persisted = [
        check_turn(view, payload["request_id"], 1)
        for view, payload in zip(views, payloads)
    ]
    output: dict[str, Any] = {
        "simultaneous_send": summary(results),
        "persisted_ready": sum(persisted),
    }
    if not all(is_done(r) for r in results) or not all(persisted):
        output["passed"] = False
        return output
    client, conversation = clients[0], conversations[0]
    same = body(1, "One request submitted twice at once", team)
    duplicate = parallel_send([(clone(client), conversation, same) for _ in range(2)])
    current = snapshot(client, conversation)
    duplicate_ok = check_turn(current, same["request_id"], 2)
    duplicate_ok = (
        duplicate_ok
        and any(is_done(r) for r in duplicate)
        and all(
            is_done(r)
            or (r["status"] == 200 and r["terminal"] == "pending")
            or (r["status"] == 409 and r["code"] == "chat_busy")
            for r in duplicate
        )
    )
    output["same_request_race"] = {
        **summary(duplicate),
        "one_persisted_turn": duplicate_ok,
    }
    replay = parallel_send([(clone(client), conversation, same) for _ in range(10)])
    replay_ok = all(is_done(r) for r in replay) and check_turn(
        snapshot(client, conversation), same["request_id"], 2
    )
    output["completed_replay"] = {**summary(replay), "unchanged_history": replay_ok}
    competitors = [body(2, f"Competing send {i}", team) for i in range(2)]
    raced = parallel_send([(clone(client), conversation, item) for item in competitors])
    winner = [i for i, result in enumerate(raced) if is_done(result)]
    loser = [r for r in raced if r["status"] == 409 and r["code"] == "chat_busy"]
    race_ok = len(winner) == 1 and len(loser) == 1
    if race_ok:
        race_ok = check_turn(
            snapshot(client, conversation), competitors[winner[0]]["request_id"], 3
        )
    output["different_request_race"] = {**summary(raced), "one_winner": race_ok}
    foreign = clients[1].call("GET", f"/api/v1/conversations/{conversation}")
    output["foreign_account_hidden"] = foreign.status == 404
    output["passed"] = duplicate_ok and replay_ok and race_ok and foreign.status == 404
    return output


def prepare_agents(
    client: Client, account: dict[str, Any], count: int
) -> list[dict[str, Any]]:
    versions = []
    for index in range(count):
        created = decoded(
            client.call(
                "POST",
                f"/api/v1/groups/{account['group_id']}/agents",
                {
                    "name": f"Synthetic chat {uuid.uuid4().hex[:10]} {index}",
                    "visibility": "private",
                },
                Idempotency_Key=str(uuid.uuid4()),
            ),
            (201,),
        )
        draft = created["versions"][0]
        saved = decoded(
            client.call(
                "PATCH",
                f"/api/v1/agent-versions/{draft['id']}",
                {
                    "expected_revision": draft["revision"],
                    "agent_md": "You are a synthetic test assistant. Answer clearly and briefly.",
                },
            )
        )
        published = decoded(
            client.call(
                "POST",
                f"/api/v1/agent-versions/{draft['id']}/publish",
                {"expected_revision": saved["revision"]},
                Idempotency_Key=str(uuid.uuid4()),
            )
        )
        if published.get("state") != "published":
            raise RuntimeError("Synthetic Agent did not publish")
        versions.append({"version_id": published["id"]})
    return versions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--agent-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.account_file.read_text(encoding="utf-8"))
    base = config["base_url"].rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "gateway",
        "gateway.local",
    }:
        parser.error("Only an isolated local HTTP service is supported")
    accounts = config["accounts"][: args.users]
    if len(accounts) != args.users or args.users < 2:
        parser.error("Need the requested number of distinct accounts, at least two")
    if len({a["username"] for a in accounts}) != args.users:
        parser.error("Accounts must be distinct")
    report: dict[str, Any] = {
        "users": args.users,
        "provider_mode": "isolated_mock",
        "phases": {},
        "passed": False,
    }
    try:
        clients: list[Client] = []
        catalogs: list[list[dict[str, Any]]] = []
        for account in accounts:
            client = new_client(base, args.timeout)
            auth = decoded(
                client.call(
                    "POST",
                    "/api/v1/auth/login",
                    {"username": account["username"], "password": account["password"]},
                )
            )
            client.csrf = auth["csrf_token"]
            if (
                auth["user"]["id"] != account["user_id"]
                or auth["user"]["username"] != account["username"]
            ):
                raise RuntimeError("Account identity mismatch")
            available = prepare_agents(client, account, 1 if args.agent_only else 2)
            clients.append(client)
            catalogs.append(available)
        conversations = [
            decoded(
                client.call(
                    "POST",
                    "/api/v1/conversations",
                    {"version_id": catalog[0]["version_id"]},
                )
            )["id"]
            for client, catalog in zip(clients, catalogs)
        ]
        report["phases"]["agent"] = run_phase(clients, conversations, False)
        print(json.dumps({"agent": report["phases"]["agent"]}), flush=True)
        if not args.agent_only:
            conversations = []
            for index, (client, account, catalog) in enumerate(
                zip(clients, accounts, catalogs)
            ):
                team = decoded(
                    client.call(
                        "POST",
                        f"/api/v1/courses/{account['course_id']}/teams",
                        {
                            "display_name": f"Synthetic load Team {uuid.uuid4().hex[:8]}",
                            "visibility": "private",
                            "members": [
                                {
                                    "agent_version_id": agent["version_id"],
                                    "position": position,
                                    "is_leader": position == 0,
                                }
                                for position, agent in enumerate(catalog[:2])
                            ],
                        },
                        Idempotency_Key=str(uuid.uuid4()),
                    ),
                    (201,),
                )
                created = decoded(
                    client.call(
                        "POST",
                        "/api/v1/conversations",
                        {"entry": {"kind": "team", "team_id": team["id"]}},
                    )
                )
                conversations.append(created["id"])
            report["phases"]["team"] = run_phase(clients, conversations, True)
            print(json.dumps({"team": report["phases"]["team"]}), flush=True)
        report["passed"] = all(phase["passed"] for phase in report["phases"].values())
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
        report["error"] = (
            str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        )
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "users": args.users}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
