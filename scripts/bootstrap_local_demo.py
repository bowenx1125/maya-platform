"""Create local-only Demo credentials and a random session secret safely."""

from __future__ import annotations

import argparse
import csv
import getpass
import io
import ipaddress
import os
import re
import secrets
import socket
import stat
import subprocess
import tempfile
from pathlib import Path

FIXED_USERS = (
    ("maya", "maya", "Maya", "teacher", ""),
    ("bowen", "bowen", "Bowen", "student", "group-demo"),
    ("kaikai", "kaikai", "Kaikai", "student", "group-demo"),
    ("jade", "jade", "Jade", "student", "group-demo"),
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
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if os.name == "nt":
                _restrict_windows_acl(temporary)
            else:
                os.fchmod(handle.fileno(), stat.S_IRUSR | stat.S_IWUSR)
            handle.write(content)
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary.exists():
            temporary.unlink()


def _restrict_windows_acl(path: Path) -> None:
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = list(csv.reader(io.StringIO(identity.stdout)))
    sid = rows[0][1] if len(rows) == 1 and len(rows[0]) == 2 else ""
    if not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
        raise RuntimeError("cannot identify the current Windows account")
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
        capture_output=True,
        text=True,
        check=True,
    )


GATEWAY_PORT = 8080

# A classroom LAN is an RFC1918 network. Wider "private" ranges - CGNAT,
# link-local, and the 198.18/15 benchmarking block a VPN often installs - are
# reachable from this host but not from a student's phone, so a QR code built
# on one leads nowhere.
_LAN_BLOCKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)


def _is_classroom_lan(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in block for block in _LAN_BLOCKS)


def _route_probe_address() -> str:
    """The local address the routing table would use for off-host traffic."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packet is sent; this only consults the routing table.
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        return ""
    finally:
        probe.close()


def detect_private_lan_origin() -> str:
    """This machine's classroom-LAN origin on the Compose gateway port.

    An empty ``CLASSROOM_PUBLIC_BASE_URL`` allows no origin at all, so every
    mutation on a freshly bootstrapped Demo fails the CSRF origin check and
    the UI reports only that the form expired. The value also has to satisfy
    two rules at once: the classroom QR code rejects loopback and needs a
    private-LAN address, while the CSRF check compares the port. Loopback on
    the same port is then accepted too, so ``http://localhost:8080`` keeps
    working for local use.

    An empty result is returned rather than a guess when no classroom LAN is
    found; ``docs/`` explains how to set the value by hand.
    """

    candidates = [_route_probe_address()]
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    for address in candidates:
        if address and _is_classroom_lan(address):
            return f"http://{address}:{GATEWAY_PORT}"
    return ""


def build_env(session_secret: str) -> str:
    values = {
        "NODE_ENV": "development",
        "DEMO_MODE": "true",
        "DEMO_QUICK_LOGIN": "true",
        "SESSION_SECRET": session_secret,
        "CLASSROOM_PUBLIC_BASE_URL": detect_private_lan_origin(),
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
        "with mode 0600 for 4 fixed Demo identities."
    )
    print("Provider selectors default to mock; supplier keys were not written.")


if __name__ == "__main__":
    main()
