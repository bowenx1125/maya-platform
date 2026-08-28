"""Create local-only Demo credentials and a random session secret safely."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import stat
import tempfile
from pathlib import Path

FIXED_USERS = (
    ("teacher-demo", "teacher-demo", "Demo Teacher", "teacher", ""),
    ("student-bowen-1", "student-bowen-1", "Bowen Student 1", "student", "group-bowen"),
    ("student-bowen-2", "student-bowen-2", "Bowen Student 2", "student", "group-bowen"),
    ("student-bowen-3", "student-bowen-3", "Bowen Student 3", "student", "group-bowen"),
    ("student-kaikai-1", "student-kaikai-1", "KaiKai Student 1", "student", "group-kaikai"),
    ("student-kaikai-2", "student-kaikai-2", "KaiKai Student 2", "student", "group-kaikai"),
    ("student-kaikai-3", "student-kaikai-3", "KaiKai Student 3", "student", "group-kaikai"),
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
        help="explicitly replace existing ignored .env/accounts.private.md files",
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
    if not 6 <= len(first) <= 4096:
        raise SystemExit("Demo password must contain 6 to 4096 characters")
    if "|" in first or any(ord(character) < 0x20 for character in first):
        raise SystemExit("Demo password cannot contain Markdown separators or control characters")
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
        "DEMO_QUICK_LOGIN": "true",
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
        "ALLOW_LEGACY_DEMO_USERS": "false",
    }
    return "".join(f"{name}={value}\n" for name, value in values.items())


def build_accounts_markdown(password: str) -> str:
    header = (
        "# Maya Demo account catalog\n\n"
        "| account_key | username | display_name | password | role | group |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )
    rows = "".join(
        f"| {account_key} | {username} | {display_name} | {password} | {role} | {group} |\n"
        for account_key, username, display_name, role, group in FIXED_USERS
    )
    return header + rows


def main() -> None:
    args = parse_args()
    product_root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    env_path = product_root / ".env"
    accounts_path = product_root / "backend" / "config" / "demo-accounts" / "accounts.private.md"
    existing = [path for path in (env_path, accounts_path) if path.exists()]
    if existing and not args.force:
        names = ", ".join(str(path.relative_to(product_root)) for path in existing)
        raise SystemExit(
            f"refusing to overwrite {names}; rerun with --force only after confirming replacement"
        )

    password, generated = choose_password(args.generate_password)
    session_secret = secrets.token_urlsafe(48)
    env_content = build_env(session_secret)
    accounts_content = build_accounts_markdown(password)

    written: list[Path] = []
    try:
        write_private(env_path, env_content, args.force)
        written.append(env_path)
        write_private(accounts_path, accounts_content, args.force)
        written.append(accounts_path)
    except Exception:
        if not args.force:
            for path in written:
                path.unlink(missing_ok=True)
        raise

    if generated:
        print(f"Generated shared Demo password (displayed once): {password}")
    print(
        "Created ignored .env and backend/config/demo-accounts/accounts.private.md "
        "with mode 0600 for 7 fixed Demo identities."
    )
    print("Provider selectors default to mock; supplier keys were not written.")


if __name__ == "__main__":
    main()
