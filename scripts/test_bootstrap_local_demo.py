"""Deterministic safety probes for bootstrap_local_demo.py using a temp root."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    script = Path(__file__).with_name("bootstrap_local_demo.py")
    with tempfile.TemporaryDirectory(prefix="maya-bootstrap-test-") as directory:
        root = Path(directory)
        command = [sys.executable, str(script), "--root", str(root), "--generate-password"]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        if first.returncode != 0:
            raise SystemExit(first.stderr or first.stdout)
        password_match = re.search(
            r"Generated shared Demo password \(displayed once\): ([^\n]+)", first.stdout
        )
        if not password_match:
            raise AssertionError("generated password was not displayed exactly once")
        password = password_match.group(1).strip()
        env_path = root / ".env"
        accounts_path = root / "backend/config/demo-accounts/accounts.private.md"
        if os.name == "nt":
            for path in (env_path, accounts_path):
                acl_raw = subprocess.run(
                    ["icacls", str(path)], capture_output=True, check=True
                ).stdout
                # icacls prints localized text in the ANSI code page; text=True
                # fails outright under a UTF-8 mode interpreter.
                acl = acl_raw.decode("mbcs", errors="replace").splitlines()[0]
                if acl.count(":(F)") != 1 or "(I)" in acl:
                    raise AssertionError(
                        "bootstrap files must have one non-inherited full-access ACE"
                    )
        elif stat_mode(env_path) != 0o600 or stat_mode(accounts_path) != 0o600:
            raise AssertionError("bootstrap files must be mode 0600")
        env_values = dict(
            line.split("=", 1)
            for line in env_path.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        if len(env_values.get("SESSION_SECRET", "").encode()) < 32:
            raise AssertionError("session secret is shorter than 32 bytes")
        for key in ("DASHSCOPE_API_KEY", "DEEPL_API_KEY", "FALLBACK_VOICE_PROFILE_ID"):
            if env_values.get(key):
                raise AssertionError(f"supplier setting unexpectedly populated: {key}")
        rows = [
            line
            for line in accounts_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("| ") and "account_key" not in line and "---" not in line
        ]
        if len(rows) != 4 or not all(f"| {password} |" in row for row in rows):
            raise AssertionError(
                "all seven fixed identities must share the generated Demo password"
            )
        second = subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--generate-password"],
            capture_output=True,
            text=True,
            check=False,
        )
        if second.returncode == 0:
            raise AssertionError("bootstrap must refuse overwrite without --force")
    print(
        "bootstrap_local_demo safety probe passed: private account catalog, random secret, "
        "restricted permissions, blank supplier keys, and overwrite refusal"
    )


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    main()
