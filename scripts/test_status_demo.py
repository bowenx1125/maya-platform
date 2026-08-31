"""Deterministic checks for the browser-routed Demo status probe."""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import status_demo  # noqa: E402, I001


SAFE_STATUS: dict[str, Any] = {
    "baseline": {"usable": True},
    "composition": {"components": [{"label": "Embedding", "mode": "mock"}]},
    "dirty_agents": 0,
    "dirty_debates": 0,
    "dirty_interactions": 0,
}


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self._payload).encode("utf-8")


def _run_main(monkeypatch_module: ModuleType, response: object) -> tuple[int | None, str, str]:
    paths: list[str] = []

    def fake_urlopen(request: Any, timeout: int) -> _Response:
        paths.append(request.full_url)
        return _Response(response)

    monkeypatch_module.urlopen = fake_urlopen
    old_argv = sys.argv
    sys.argv = ["status_demo.py", "--url", "http://fixture.test"]
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status_demo.main()
            except SystemExit as exc:
                return_code = int(exc.code) if isinstance(exc.code, int) else 1
            else:
                return_code = None
    finally:
        sys.argv = old_argv
    if paths != ["http://fixture.test/api/v1/demo/status"]:
        raise AssertionError(f"status probe used unexpected paths: {paths!r}")
    return return_code, stdout.getvalue(), stderr.getvalue()


def test_successful_status_is_readiness(monkeypatch_module: ModuleType = status_demo) -> None:
    return_code, output, error = _run_main(monkeypatch_module, SAFE_STATUS)
    if return_code is not None or error:
        raise AssertionError(f"successful status probe failed: {return_code=} {error=}")
    if "Readiness: ready" not in output or "Dirty work: Agents=0" not in output:
        raise AssertionError(f"status probe omitted safe readiness output: {output!r}")


def test_http_error_fails_closed() -> None:
    paths: list[str] = []

    def fake_urlopen(request: Any, timeout: int) -> _Response:
        paths.append(request.full_url)
        raise HTTPError(request.full_url, 503, "fixture unavailable", {}, None)

    status_demo.urlopen = fake_urlopen
    old_argv = sys.argv
    sys.argv = ["status_demo.py", "--url", "http://fixture.test"]
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            try:
                status_demo.main()
            except SystemExit as exc:
                if exc.code != 1:
                    raise AssertionError(
                        f"HTTPError returned wrong exit code: {exc.code!r}"
                    ) from None
            else:
                raise AssertionError("HTTPError unexpectedly passed")
    finally:
        sys.argv = old_argv
    if paths != ["http://fixture.test/api/v1/demo/status"]:
        raise AssertionError(f"HTTPError probe used unexpected paths: {paths!r}")
    if "Maya Demo unavailable: HTTPError" not in stdout.getvalue():
        raise AssertionError("HTTPError was not reported with a safe message")


def test_invalid_status_payload_fails_closed() -> None:
    return_code, output, error = _run_main(status_demo, ["not", "a", "status"])
    if return_code != 1 or error:
        raise AssertionError(f"invalid payload returned unexpected result: {return_code=} {error=}")
    if "invalid safe status payload" not in output:
        raise AssertionError("invalid payload was not rejected")


def main() -> None:
    test_successful_status_is_readiness()
    test_http_error_fails_closed()
    test_invalid_status_payload_fails_closed()
    print("status_demo probe passed: routed 200 readiness, HTTPError, and invalid payload")


if __name__ == "__main__":
    main()
