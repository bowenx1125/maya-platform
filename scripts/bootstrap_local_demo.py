"""Create local-only Demo credentials and a random session secret safely."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pwdlib import PasswordHash

FIXED_USERS = (
    ("98644172-6bbb-5383-8198-3b78dcd5b9ab", "teacher-demo"),
    ("bad7de3c-0409-5d50-9ad7-bbb641d1f6a7", "student-bowen-1"),
    ("7ff99250-0829-5864-8040-b3133510e7da", "student-bowen-2"),
    ("4d2445fe-7c7b-55ff-8c4c-778ab5098c1d", "student-bowen-3"),
    ("0c12d01a-5acf-5430-bc4d-731af768ff46", "student-kaikai-1"),
    ("d4465e7b-7b76-5ac1-8f6e-5ce6a6da737d", "student-kaikai-2"),
    ("fc2604c6-c760-53e5-b69b-c3a1ef471ea8", "student-kaikai-3"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="generate and display a shared Demo password once instead of prompting",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="explicitly replace existing ignored .env/demo_users.yaml files",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def choose_password(generate: bool) -> tuple[str, bool]:
    if generate:
        return secrets.token_urlsafe(18), True
    first = getpass.getpass("Shared Demo password (leave blank to generate one): ")
    if not first:
        return secrets.token_urlsafe(18), True
    if len(first) < 12:
        raise SystemExit("Demo password must contain at least 12 characters")
    confirmation = getpass.getpass("Repeat shared Demo password: ")
    if first != confirmation:
        raise SystemExit("Demo password confirmation did not match")
    return first, False


def write_private(path: Path, content: str, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        raise FileExistsError(path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_env(session_secret: str) -> str:
    values = {
        "NODE_ENV": "development",
        "DEMO_MODE": "true",
        "SESSION_SECRET": session_secret,
        "CLASSROOM_PUBLIC_BASE_URL": "",
        "DASHSCOPE_API_KEY": "",
        "DASHSCOPE_WORKSPACE_ID": "",
        "DASHSCOPE_REGION": "",
        "DEEPL_API_KEY": "",
        "LLM_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "mock",
        "TTS_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "TRANSLATION_PROVIDER": "mock",
        "FALLBACK_VOICE_PROFILE_ID": "",
        "MAYA_ENV": "",
    }
    return "".join(f"{name}={value}\n" for name, value in values.items())


def build_credentials(password: str) -> str:
    hasher = PasswordHash.recommended()
    payload: dict[str, Any] = {
        "users": [
            {
                "user_id": user_id,
                "username": username,
                "password_hash": hasher.hash(password),
            }
            for user_id, username in FIXED_USERS
        ]
    }
    return yaml.safe_dump(payload, sort_keys=False)


def main() -> None:
    args = parse_args()
    product_root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    env_path = product_root / ".env"
    credentials_path = product_root / "backend" / "config" / "demo_users.yaml"
    existing = [path for path in (env_path, credentials_path) if path.exists()]
    if existing and not args.force:
        names = ", ".join(str(path.relative_to(product_root)) for path in existing)
        raise SystemExit(f"refusing to overwrite {names}; rerun with --force only after confirming replacement")

    password, generated = choose_password(args.generate_password)
    session_secret = secrets.token_urlsafe(48)
    env_content = build_env(session_secret)
    credentials_content = build_credentials(password)

    written: list[Path] = []
    try:
        write_private(env_path, env_content, args.force)
        written.append(env_path)
        write_private(credentials_path, credentials_content, args.force)
        written.append(credentials_path)
    except Exception:
        if not args.force:
            for path in written:
                path.unlink(missing_ok=True)
        raise

    if generated:
        print(f"Generated shared Demo password (displayed once): {password}")
    print("Created ignored .env and backend/config/demo_users.yaml with mode 0600 for 7 fixed Demo identities.")
    print("Provider selectors default to mock; supplier keys were not written.")


if __name__ == "__main__":
    main()
