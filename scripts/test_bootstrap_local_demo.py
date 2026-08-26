"""Deterministic safety probes for bootstrap_local_demo.py using a temp root."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from pwdlib import PasswordHash


def main() -> None:
    script = Path(__file__).with_name("bootstrap_local_demo.py")
    with tempfile.TemporaryDirectory(prefix="maya-bootstrap-test-") as directory:
        root = Path(directory)
        command = [sys.executable, str(script), "--root", str(root), "--generate-password"]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        if first.returncode != 0:
            raise SystemExit(first.stderr or first.stdout)
        password_match = re.search(r"Generated shared Demo password \(displayed once\): ([^\n]+)", first.stdout)
        if not password_match:
            raise AssertionError("generated password was not displayed exactly once")
        password = password_match.group(1).strip()
        env_path = root / ".env"
        credentials_path = root / "backend/config/demo_users.yaml"
        if stat_mode(env_path) != 0o600 or stat_mode(credentials_path) != 0o600:
            raise AssertionError("bootstrap files must be mode 0600")
        env_values = dict(line.split("=", 1) for line in env_path.read_text(encoding="utf-8").splitlines() if "=" in line)
        if len(env_values.get("SESSION_SECRET", "").encode()) < 32:
            raise AssertionError("session secret is shorter than 32 bytes")
        for key in ("DASHSCOPE_API_KEY", "DEEPL_API_KEY", "FALLBACK_VOICE_PROFILE_ID"):
            if env_values.get(key):
                raise AssertionError(f"supplier setting unexpectedly populated: {key}")
        users = yaml.safe_load(credentials_path.read_text(encoding="utf-8"))["users"]
        if len(users) != 7 or not all(PasswordHash.recommended().verify(password, row["password_hash"]) for row in users):
            raise AssertionError("all seven fixed identities must share the generated password hash")
        second = subprocess.run([sys.executable, str(script), "--root", str(root), "--generate-password"], capture_output=True, text=True, check=False)
        if second.returncode == 0:
            raise AssertionError("bootstrap must refuse overwrite without --force")
    print("bootstrap_local_demo safety probe passed: hashes, random secret, mode 0600, blank supplier keys, and overwrite refusal")


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    main()
