#!/usr/bin/env python3
"""Safely verify Maya's DashScope environment with one minimal real request.

The script reads maya-platform/.env, never prints the API key, and calls the
Beijing workspace-specific OpenAI-compatible Chat Completions endpoint.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / "maya-platform" / ".env"
DEFAULT_MODEL = "qwen-plus"
EXPECTED_REPLY = "MAYA_ENV_OK"


def fail(message: str, exit_code: int) -> NoReturn:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        fail(f"Environment file not found: {path}", 2)

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def required(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        fail(f"{name} is missing or empty in .env", 2)
    return value


def sanitized_error(raw: str, api_key: str) -> str:
    return raw.replace(api_key, "<redacted-api-key>")[:1500]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Maya's DASHSCOPE_* settings without printing secrets."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Path to .env (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Small model used for the test (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--endpoint",
        choices=("workspace", "shared", "trial"),
        default="workspace",
        help=(
            "Endpoint type: workspace validates the configured Workspace ID; "
            "shared validates the Beijing API key without using Workspace ID; "
            "trial uses the lower-limit trial endpoint (default: workspace)."
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate local variables without making an API request.",
    )
    args = parser.parse_args()

    env_path = args.env_file.expanduser().resolve()
    values = load_env_file(env_path)
    api_key = required(values, "DASHSCOPE_API_KEY")
    region = required(values, "DASHSCOPE_REGION")

    if region != "cn-beijing":
        fail(
            f"DASHSCOPE_REGION must be cn-beijing for the frozen Maya Demo; got {region!r}",
            2,
        )

    workspace_id = values.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    if args.endpoint == "workspace":
        if not workspace_id:
            fail("DASHSCOPE_WORKSPACE_ID is missing or empty in .env", 2)
        if not re.fullmatch(r"[A-Za-z0-9-]+", workspace_id):
            fail("DASHSCOPE_WORKSPACE_ID contains unexpected characters", 2)

    print(f"[OK] Loaded environment file: {env_path}")
    print("[OK] DASHSCOPE_API_KEY is configured (value hidden)")
    if workspace_id:
        print(f"[OK] Workspace ID is configured (length={len(workspace_id)}, value hidden)")
    else:
        print("[INFO] Workspace ID is empty; shared/trial testing can still continue")
    print(f"[OK] Region: {region}")

    if args.check_only:
        print("[OK] Local configuration is complete; no network request was made.")
        return 0

    if args.endpoint == "workspace":
        host = f"{workspace_id}.cn-beijing.maas.aliyuncs.com"
    elif args.endpoint == "shared":
        host = "dashscope.aliyuncs.com"
    else:
        host = "trial.cn-beijing.maas.aliyuncs.com"
    url = f"https://{host}/compatible-mode/v1/chat/completions"
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": f"Reply with exactly this text and nothing else: {EXPECTED_REPLY}",
            }
        ],
        "temperature": 0,
        "max_tokens": 16,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "maya-dashscope-env-check/1.0",
        },
    )

    print(
        f"[INFO] Sending one minimal real request with model={args.model!r} "
        f"via endpoint={args.endpoint!r} ..."
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = sanitized_error(body, api_key)
        if exc.code in {401, 403}:
            fail(
                f"HTTP {exc.code}: API key, workspace ownership, region, IP whitelist, "
                f"or model permission is invalid. Provider response: {detail}",
                3,
            )
        if "Workspace endpoint is invalid" in body:
            fail(
                f"HTTP {exc.code}: Workspace ID is not a valid Beijing workspace endpoint. "
                "Copy the real Workspace ID/API Host from the Bailian console; do not use "
                "the workspace display name, account ID, or the documentation placeholder "
                f"llm-xxx. To test the key separately, rerun with --endpoint shared. "
                f"Provider response: {detail}",
                3,
            )
        fail(f"HTTP {exc.code}: Provider response: {detail}", 3)
    except urllib.error.URLError as exc:
        fail(f"Network/TLS/DNS error: {sanitized_error(str(exc.reason), api_key)}", 4)
    except TimeoutError:
        fail("Request timed out after 30 seconds", 4)

    if status != 200:
        fail(f"Unexpected HTTP status: {status}", 3)

    try:
        data = json.loads(body)
        reply = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        fail(f"HTTP 200 but the response schema was unexpected: {type(exc).__name__}", 3)

    print("[OK] HTTP 200 received")
    print("[OK] API key, workspace, region, and model are usable")
    print(f"[INFO] Model reply: {reply!r}")
    if reply != EXPECTED_REPLY:
        print("[WARN] The model reply differed, but authentication and model access succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
