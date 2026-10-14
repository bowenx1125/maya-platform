#!/usr/bin/env python3
"""Read-mostly dual-account API smoke against Maya production (or a base URL).

This is automation evidence only. It must never be treated as a human visual
PASS. Passwords come from the environment (or the classroom username-double
convention) and are never printed or written to reports.

Env:
  MAYA_BASE_URL          default https://app.mayaform.net
  MAYA_TEACHER_USER      default Maya
  MAYA_TEACHER_PASS      optional; else username + username.lower()
  MAYA_STUDENT_USER      default Guyue
  MAYA_STUDENT_PASS      optional; else username + username.lower()
  MAYA_SMOKE_WRITE       set to 1 to allow a harmless CSRF-authenticated
                         GET-only session (still no content writes)

Exit 0 on all checks green; non-zero otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any


def _password(username: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    # Classroom test convention from acceptance notes; never log the value.
    return f"{username}{username.lower()}"


def _origin(base: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise SystemExit(f"invalid MAYA_BASE_URL: {base}")
    return f"{parsed.scheme}://{parsed.netloc}"


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.origin = _origin(self.base)
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf: str | None = None

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base}{path}"

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        expect: int | tuple[int, ...] = 200,
    ) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "Origin": self.origin,
            "Referer": f"{self.origin}/",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(
            self._url(path), data=data, headers=headers, method=method.upper()
        )
        try:
            with self.opener.open(req, timeout=30) as resp:
                status = resp.getcode()
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
            payload: Any
            try:
                payload = json.loads(raw.decode("utf-8") or "null")
            except json.JSONDecodeError:
                payload = {"_raw": raw[:200].decode("utf-8", "replace")}
            allowed = expect if isinstance(expect, tuple) else (expect,)
            if status not in allowed:
                raise AssertionError(
                    f"{method} {path} -> {status}, expected {allowed}; body={payload!r}"
                ) from None
            return payload
        payload = json.loads(raw.decode("utf-8") or "null") if raw else None
        allowed = expect if isinstance(expect, tuple) else (expect,)
        if status not in allowed:
            raise AssertionError(
                f"{method} {path} -> {status}, expected {allowed}; body={payload!r}"
            )
        return payload

    def login(self, username: str, password: str) -> dict[str, Any]:
        session = self.request(
            "POST",
            "/api/v1/auth/login",
            {"username": username, "password": password},
        )
        if not isinstance(session, dict) or "csrf_token" not in session:
            raise AssertionError("login response missing csrf_token")
        self.csrf = session["csrf_token"]
        return session

    def logout(self) -> None:
        try:
            self.request("POST", "/api/v1/auth/logout", {}, expect=(200, 204))
        except AssertionError:
            pass
        self.csrf = None


def check_root(base: str) -> None:
    origin = _origin(base)
    req = urllib.request.Request(origin + "/", method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.getcode() != 200:
            raise AssertionError(f"GET / -> {resp.getcode()}")


def run_teacher(client: Client, username: str, password: str) -> list[str]:
    results: list[str] = []
    session = client.login(username, password)
    user = session["user"]
    results.append(f"teacher.login role_courses={len(user.get('courses') or [])}")
    me = client.request("GET", "/api/v1/auth/me")
    results.append(f"teacher.me username={me['user']['username']}")
    courses = [
        c for c in (me["user"].get("courses") or []) if c.get("role") == "teacher"
    ]
    if not courses:
        raise AssertionError("teacher has no teacher course membership")
    course_id = courses[0]["course_id"]
    debates = client.request("GET", f"/api/v1/courses/{course_id}/debates")
    results.append(f"teacher.debates count={len(debates) if isinstance(debates, list) else '?'}")
    live = client.request("GET", f"/api/v1/courses/{course_id}/live")
    results.append(f"teacher.live type={type(live).__name__}")
    voices = client.request(
        "GET", f"/api/v1/courses/{course_id}/voice-profiles"
    )
    results.append(
        f"teacher.voices count={len(voices) if isinstance(voices, list) else '?'}"
    )
    templates = client.request("GET", "/api/v1/avatar-templates")
    results.append(
        f"teacher.avatar_templates count={len(templates) if isinstance(templates, list) else '?'}"
    )
    client.logout()
    return results


def run_student(client: Client, username: str, password: str) -> list[str]:
    results: list[str] = []
    session = client.login(username, password)
    user = session["user"]
    results.append(f"student.login groups={len(user.get('groups') or [])}")
    me = client.request("GET", "/api/v1/auth/me")
    results.append(f"student.me username={me['user']['username']}")
    groups = me["user"].get("groups") or []
    if groups:
        group_id = groups[0]["group_id"]
        voices = client.request("GET", f"/api/v1/groups/{group_id}/voice-profiles")
        results.append(
            f"student.voices count={len(voices) if isinstance(voices, list) else '?'}"
        )
        overview = client.request(
            "GET", f"/api/v1/groups/{group_id}", expect=(200, 404)
        )
        results.append(f"student.group type={type(overview).__name__}")
    else:
        results.append("student.groups empty")
    courses = me["user"].get("courses") or []
    if courses:
        course_id = courses[0]["course_id"]
        live = client.request(
            "GET", f"/api/v1/courses/{course_id}/live", expect=(200, 403, 404)
        )
        results.append(f"student.live type={type(live).__name__}")
    templates = client.request("GET", "/api/v1/avatar-templates")
    results.append(
        f"student.avatar_templates count={len(templates) if isinstance(templates, list) else '?'}"
    )
    client.logout()
    return results


def main() -> int:
    base = os.environ.get("MAYA_BASE_URL", "https://app.mayaform.net").rstrip("/")
    teacher_user = os.environ.get("MAYA_TEACHER_USER", "Maya")
    student_user = os.environ.get("MAYA_STUDENT_USER", "Guyue")
    teacher_pass = _password(teacher_user, os.environ.get("MAYA_TEACHER_PASS"))
    student_pass = _password(student_user, os.environ.get("MAYA_STUDENT_PASS"))

    print(f"base={base}")
    print("mode=api_smoke (NOT human visual PASS)")
    failures: list[str] = []
    lines: list[str] = []

    try:
        check_root(base)
        lines.append("root.GET 200")
    except Exception as exc:  # noqa: BLE001 — report and continue other checks
        failures.append(f"root: {exc}")

    teacher = Client(base)
    try:
        lines.extend(run_teacher(teacher, teacher_user, teacher_pass))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"teacher: {exc}")

    student = Client(base)
    try:
        lines.extend(run_student(student, student_user, student_pass))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"student: {exc}")

    for line in lines:
        print(f"PASS {line}")
    for fail in failures:
        print(f"FAIL {fail}", file=sys.stderr)

    print(
        f"summary checks={len(lines)} failures={len(failures)} "
        f"(automation only; do not mark human PASS)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
