"""Private Demo account catalog parsing and password verification.

The Demo account catalog is deliberately a small Markdown file instead of a
second account database. It is read as a complete document, validated before
it is used, and converted to an immutable desired graph. The account key is
never part of a public DTO; it is only the stable input to :func:`account_id`
used by the synchroniser in :mod:`app.modules.auth.service`.

``demo_users.yaml`` is retained solely as an explicit test/migration fallback
for old isolated Wave 0 fixtures. When an ``accounts.private.md`` file is
present it is the only source consulted.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

import yaml
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.hash_gate import hash_slot
from app.core.identity import username_key

# This is the frozen Wave 0 seed namespace. Keeping the canonical account
# keys equal to the existing seed keys means the first private catalog sync
# reuses the seven historical User UUIDs. New keys are deterministic UUIDv5
# values and therefore survive remove/re-add without a new identity.
ACCOUNT_NAMESPACE = UUID("a7cea9e2-390f-5b48-b129-4f388b0362e3")
CATALOG_MAX_BYTES = 1_048_576

AccountRole = Literal["teacher", "student"]

_ACCOUNT_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HEADER_NAMES = {
    "account_key",
    "username",
    "display_name",
    "password",
    "role",
    "group",
}
_TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class DemoAccount:
    """One validated private catalog row.

    ``password`` is intentionally an internal-only value. This object never
    crosses the router boundary and no ``repr``/log helper includes it.
    """

    account_key: str = field(repr=False)
    username: str = field(repr=False)
    display_name: str
    password: str = field(repr=False)
    role: AccountRole
    group_key: str | None = field(repr=False)
    # Only legacy migration snapshots populate this with an existing Argon2
    # hash. Private Markdown accounts use the plaintext ``password`` above;
    # neither value is ever serialized or logged.
    password_hash: str | None = field(default=None, repr=False)

    @property
    def user_id(self) -> str:
        return account_id(self.account_key)


@dataclass(frozen=True)
class DesiredAccountGraph:
    """The complete, validated identity graph requested by the private file."""

    accounts: tuple[DemoAccount, ...]

    @property
    def by_key(self) -> dict[str, DemoAccount]:
        return {account.account_key: account for account in self.accounts}

    @property
    def user_ids(self) -> frozenset[str]:
        return frozenset(account.user_id for account in self.accounts)


@dataclass(frozen=True)
class DemoAccountSnapshot:
    """Immutable process snapshot used by every auth read after startup."""

    graph: DesiredAccountGraph
    # The synchronizer may bind a non-canonical key to an existing seeded UUID.
    # Keep the resolved mapping in the post-commit snapshot; deterministic IDs
    # are used only before the first successful synchronization.
    resolved_user_ids: tuple[tuple[str, str], ...] = ()

    @property
    def accounts(self) -> tuple[DemoAccount, ...]:
        return self.graph.accounts

    @property
    def by_key(self) -> dict[str, DemoAccount]:
        return self.graph.by_key

    def user_id_for(self, account: DemoAccount) -> str:
        for key, user_id in self.resolved_user_ids:
            if key == account.account_key:
                return user_id
        return account.user_id

    def account_for_user_id(self, user_id: str) -> DemoAccount | None:
        return next(
            (account for account in self.accounts if self.user_id_for(account) == user_id),
            None,
        )


@dataclass(frozen=True)
class DemoCredential:
    """Compatibility shape for the old hash-based credential loader."""

    user_id: str
    username: str
    password_hash: str = field(repr=False)


class CredentialFileError(RuntimeError):
    """Raised for a missing, unsafe, or malformed runtime catalog.

    Messages are intentionally generic: account keys, usernames, paths,
    passwords, and raw Markdown lines must never enter logs or API errors.
    """


def account_id(account_key: str) -> str:
    """Return the stable platform User UUID for an immutable account key."""

    return str(uuid5(ACCOUNT_NAMESPACE, account_key))


# Entries keep a strong Settings reference intentionally: one FastAPI process
# owns one immutable settings/catalog lifetime. Keys are object identity only;
# no Engine identity or volatile fingerprint participates in authorization.
_PENDING_GRAPHS: dict[int, tuple[Settings, DesiredAccountGraph]] = {}
_CATALOG_SNAPSHOTS: dict[int, tuple[Settings, DemoAccountSnapshot]] = {}


def _pending_graph(settings: Settings) -> DesiredAccountGraph | None:
    entry = _PENDING_GRAPHS.get(id(settings))
    if entry is None or entry[0] is not settings:
        return None
    return entry[1]


def prepare_catalog(settings: Settings) -> DesiredAccountGraph:
    """Read and validate the catalog once before any DB transaction starts."""

    active = _CATALOG_SNAPSHOTS.get(id(settings))
    if active is not None and active[0] is settings:
        return active[1].graph
    pending = _pending_graph(settings)
    if pending is not None:
        return pending
    graph = load_desired_graph(settings)
    _PENDING_GRAPHS[id(settings)] = (settings, graph)
    return graph


def catalog_graph_for_sync(settings: Settings) -> DesiredAccountGraph:
    """Return the startup graph without rereading a running private file.

    A process that has already published a snapshot continues to synchronize
    that same graph.  A first synchronization gets the graph prepared by
    startup validation (or prepares it once when a test calls the service
    directly).  Explicit file reloads therefore require a new process/settings
    lifetime rather than an incidental request or sync call.
    """

    active = _CATALOG_SNAPSHOTS.get(id(settings))
    if active is not None and active[0] is settings:
        return active[1].graph
    return prepare_catalog(settings)


def active_catalog_snapshot(settings: Settings) -> DemoAccountSnapshot:
    """Return the process snapshot, never re-reading a running file."""

    entry = _CATALOG_SNAPSHOTS.get(id(settings))
    if entry is not None and entry[0] is settings:
        return entry[1]
    graph = _pending_graph(settings)
    if graph is None:
        graph = prepare_catalog(settings)
    snapshot = DemoAccountSnapshot(graph)
    _CATALOG_SNAPSHOTS[id(settings)] = (settings, snapshot)
    return snapshot


def publish_catalog_snapshot(
    settings: Settings,
    graph: DesiredAccountGraph,
    resolved_user_ids: Mapping[str, str] | None = None,
) -> DemoAccountSnapshot:
    """Publish an immutable snapshot only after the owning DB commit."""

    pairs = tuple(sorted((resolved_user_ids or {}).items()))
    snapshot = DemoAccountSnapshot(graph=graph, resolved_user_ids=pairs)
    _CATALOG_SNAPSHOTS[id(settings)] = (settings, snapshot)
    _PENDING_GRAPHS.pop(id(settings), None)
    return snapshot


def discard_pending_catalog(settings: Settings) -> None:
    """Drop a pre-transaction graph after startup synchronization fails."""

    entry = _PENDING_GRAPHS.get(id(settings))
    if entry is not None and entry[0] is settings:
        _PENDING_GRAPHS.pop(id(settings), None)
        active = _CATALOG_SNAPSHOTS.get(id(settings))
        if (
            active is not None
            and active[0] is settings
            and active[1].graph is entry[1]
            and not active[1].resolved_user_ids
        ):
            _CATALOG_SNAPSHOTS.pop(id(settings), None)


def _safe_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise CredentialFileError("demo account catalog is malformed")
    text = value.strip()
    if not text or any(ord(character) < 0x20 and character not in {"\t"} for character in text):
        raise CredentialFileError("demo account catalog is malformed")
    if "|" in text:
        raise CredentialFileError("demo account catalog is malformed")
    if field == "username" and len(text) > 120:
        raise CredentialFileError("demo account catalog is malformed")
    if field == "display_name" and len(text) > 200:
        raise CredentialFileError("demo account catalog is malformed")
    # Keep the catalog's credential boundary explicit.  The minimum permits
    # the frozen Demo password (``123456``) while rejecting accidental empty
    # or one-character credentials; the upper bound prevents an oversized
    # table cell from becoming an unbounded hashing/log-in workload.
    if field == "password" and not 6 <= len(text) <= 4096:
        raise CredentialFileError("demo account catalog is malformed")
    return text


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    if stripped.count("|") < 2 or not stripped.endswith("|"):
        raise CredentialFileError("demo account catalog is malformed")
    cells = [cell.strip() for cell in stripped[1:-1].split("|")]
    if not cells or any("\n" in cell or "\r" in cell for cell in cells):
        raise CredentialFileError("demo account catalog is malformed")
    return cells


def _is_ignored_markdown_line(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped.startswith("#")
        or stripped.startswith("<!--")
        or stripped.endswith("-->")
    )


def parse_accounts_markdown(source: str) -> DesiredAccountGraph:
    """Parse and strictly validate the private six-column Markdown table.

    The accepted schema is one table with columns ``account_key``,
    ``username``, ``display_name``, ``password``, ``role`` and ``group``. A
    leading/trailing Markdown heading or HTML comment is allowed for human
    documentation; arbitrary prose, a second table, unknown columns, duplicate
    keys, duplicate usernames, and malformed rows fail closed.
    """

    if not isinstance(source, str) or not source.strip():
        raise CredentialFileError("demo account catalog is malformed")
    lines = source.splitlines()
    header: list[str] | None = None
    separator_index: int | None = None

    for index, line in enumerate(lines):
        cells = _split_table_row(line)
        if cells is None:
            if not _is_ignored_markdown_line(line):
                raise CredentialFileError("demo account catalog is malformed")
            continue
        normalized = [cell.lower() for cell in cells]
        if set(normalized) != _HEADER_NAMES or len(normalized) != len(_HEADER_NAMES):
            raise CredentialFileError("demo account catalog is malformed")
        if header is not None:
            raise CredentialFileError("demo account catalog is malformed")
        header = normalized
        if index + 1 >= len(lines):
            raise CredentialFileError("demo account catalog is malformed")
        separator = _split_table_row(lines[index + 1])
        if separator is None or len(separator) != len(header):
            raise CredentialFileError("demo account catalog is malformed")
        if not all(_TABLE_SEPARATOR_RE.fullmatch(cell) for cell in separator):
            raise CredentialFileError("demo account catalog is malformed")
        separator_index = index + 1
        break

    if header is None or separator_index is None:
        raise CredentialFileError("demo account catalog is malformed")

    rows: list[DemoAccount] = []
    seen_keys: set[str] = set()
    seen_usernames: set[str] = set()
    for line in lines[separator_index + 1 :]:
        cells = _split_table_row(line)
        if cells is None:
            if _is_ignored_markdown_line(line):
                continue
            # A non-table line after the schema would make the catalog
            # ambiguous, so fail instead of silently accepting a partial file.
            raise CredentialFileError("demo account catalog is malformed")
        if len(cells) != len(header):
            raise CredentialFileError("demo account catalog is malformed")
        values = dict(zip(header, cells, strict=True))
        key = _safe_text(values.get("account_key"), "account_key")
        username = _safe_text(values.get("username"), "username")
        display_name = _safe_text(values.get("display_name"), "display_name")
        password = _safe_text(values.get("password"), "password")
        role_value = _safe_text(values.get("role"), "role").lower()
        group_value = values.get("group", "").strip()
        if not _ACCOUNT_KEY_RE.fullmatch(key):
            raise CredentialFileError("demo account catalog is malformed")
        if key in seen_keys or username_key(username) in seen_usernames:
            raise CredentialFileError("demo account catalog is malformed")
        if role_value not in {"teacher", "student"}:
            raise CredentialFileError("demo account catalog is malformed")
        if any(ord(character) < 0x20 for character in group_value) or "|" in group_value:
            raise CredentialFileError("demo account catalog is malformed")
        if role_value == "teacher" and group_value:
            raise CredentialFileError("demo account catalog is malformed")
        if role_value == "student" and not group_value:
            raise CredentialFileError("demo account catalog is malformed")
        seen_keys.add(key)
        seen_usernames.add(username_key(username))
        rows.append(
            DemoAccount(
                account_key=key,
                username=username,
                display_name=display_name,
                password=password,
                role=role_value,  # type: ignore[arg-type]
                group_key=group_value or None,
            )
        )

    if len({account.user_id for account in rows}) != len(rows):
        raise CredentialFileError("demo account catalog is malformed")
    return DesiredAccountGraph(tuple(rows))


def _decode_console_output(raw: bytes | None) -> str:
    """Decode localized console output using the system ANSI code page."""

    if raw is None:
        return ""
    try:
        return raw.decode("mbcs")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _private_file_permissions(path: Path, mode: int) -> bool:
    if os.name != "nt":
        return stat.S_IMODE(mode) == 0o600
    try:
        # whoami/icacls print localized text in the system's ANSI code page.
        # Decoding with text=True fails whenever that is not UTF-8 (a UTF-8
        # mode interpreter turns a decode error into a None stdout), so the
        # raw bytes are decoded explicitly and leniently instead.
        identity = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
        )
        rows = list(
            csv.reader(
                io.StringIO(_decode_console_output(identity.stdout)),
            )
        )
        if len(rows) != 1 or len(rows[0]) != 2:
            return False
        acl = subprocess.run(["icacls", str(path)], capture_output=True, check=True)
        acl_first_line = _decode_console_output(acl.stdout).splitlines()[0]
        grant = acl_first_line.removeprefix(str(path)).strip()
        return grant.casefold() in {
            f"{rows[0][0]}:(F)".casefold(),
            f"{rows[0][1]}:(F)".casefold(),
        }
    except (
        OSError,
        subprocess.CalledProcessError,
        IndexError,
        UnicodeDecodeError,
    ):
        # Any probe failure must fail closed, not propagate into startup.
        return False


def _read_secure_file(path: Path) -> bytes:
    """Read one private catalog file descriptor without following symlinks."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise CredentialFileError("demo account catalog could not be read") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CredentialFileError("demo account catalog permissions are unsafe")
        if path.is_symlink() or not _private_file_permissions(path, metadata.st_mode):
            raise CredentialFileError("demo account catalog permissions are unsafe")
        if metadata.st_size > CATALOG_MAX_BYTES:
            raise CredentialFileError("demo account catalog is too large")
        before_signature = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, CATALOG_MAX_BYTES - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > CATALOG_MAX_BYTES:
                raise CredentialFileError("demo account catalog is too large")
        after = os.fstat(descriptor)
        after_signature = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            after_signature != before_signature
            or not stat.S_ISREG(after.st_mode)
            or path.is_symlink()
            or not _private_file_permissions(path, after.st_mode)
        ):
            raise CredentialFileError("demo account catalog changed while reading")
        return b"".join(chunks)
    except CredentialFileError:
        raise
    except OSError:
        raise CredentialFileError("demo account catalog could not be read") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _load_private_graph(path: Path) -> DesiredAccountGraph:
    try:
        content = _read_secure_file(path).decode("utf-8")
    except UnicodeError:
        raise CredentialFileError("demo account catalog could not be read") from None
    return parse_accounts_markdown(content)


def _legacy_file_is_explicit(settings: Settings) -> bool:
    """Allow old YAML only for an explicit compatibility/migration path."""

    return settings.allow_legacy_demo_users


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("users")
    else:
        value = payload
    if not isinstance(value, list):
        raise CredentialFileError("legacy demo credentials are malformed")
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            raise CredentialFileError("legacy demo credentials are malformed")
        rows.append(row)
    return rows


def _load_legacy_credentials(path: Path) -> tuple[DemoCredential, ...]:
    try:
        payload = yaml.safe_load(_read_secure_file(path).decode("utf-8"))
    except UnicodeError:
        raise CredentialFileError("legacy demo credentials could not be read") from None
    except yaml.YAMLError:
        raise CredentialFileError("legacy demo credentials could not be read") from None
    credentials: list[DemoCredential] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for row in _rows(payload):
        user_id = row.get("user_id")
        username = row.get("username")
        password_hash = row.get("password_hash")
        if (
            not isinstance(user_id, str)
            or not isinstance(username, str)
            or not isinstance(password_hash, str)
        ):
            raise CredentialFileError("legacy demo credentials are malformed")
        try:
            parsed = str(UUID(user_id))
        except ValueError:
            raise CredentialFileError("legacy demo credentials are malformed") from None
        if parsed in seen_ids or username_key(username) in seen_names:
            raise CredentialFileError("legacy demo credentials are malformed")
        seen_ids.add(parsed)
        seen_names.add(username_key(username))
        if password_hash.startswith("REPLACE_"):
            # An example copied into runtime must not accidentally authenticate.
            continue
        credentials.append(DemoCredential(parsed, username, password_hash))
    return tuple(credentials)


def load_desired_graph(settings: Settings) -> DesiredAccountGraph:
    """Load the sole private catalog, with a narrow legacy test fallback."""

    private_path = settings.resolved_demo_accounts_file
    try:
        private_present = True
        os.lstat(private_path)
    except FileNotFoundError:
        private_present = False
    except OSError:
        raise CredentialFileError("demo account catalog could not be read") from None
    if private_present:
        return _load_private_graph(private_path)
    if _legacy_file_is_explicit(settings):
        legacy_path = settings.resolved_demo_users_file
        if legacy_path.exists():
            legacy = _load_legacy_credentials(legacy_path)
            accounts: list[DemoAccount] = []
            for credential in legacy:
                # Legacy rows predate account keys. Their usernames are the
                # canonical seed keys, which keeps the historical UUIDs.
                key = credential.username
                if not _ACCOUNT_KEY_RE.fullmatch(key):
                    raise CredentialFileError("legacy demo credentials are malformed")
                if key == "maya":
                    role: AccountRole = "teacher"
                    group_key: str | None = None
                elif key in ("bowen", "kaikai", "jade"):
                    role = "student"
                    group_key = "group-demo"
                else:
                    # Old YAML has no role/group fields. Unknown identities
                    # are not silently guessed into the desired graph.
                    raise CredentialFileError("legacy demo credentials are malformed")
                accounts.append(
                    DemoAccount(
                        account_key=key,
                        username=credential.username,
                        display_name=credential.username,
                        password="",
                        role=role,
                        group_key=group_key,
                        password_hash=credential.password_hash,
                    )
                )
            return DesiredAccountGraph(tuple(accounts))
    raise CredentialFileError("demo account catalog is not configured")


def verify_password(settings: Settings, username: str, password: str) -> str | None:
    """Return the configured active-catalog User UUID for a valid password."""

    try:
        snapshot = active_catalog_snapshot(settings)
        for account in snapshot.accounts:
            if username_key(account.username) != username_key(username):
                continue
            if account.password_hash is not None:
                # Gate outside the try: a busy 503 must not read as a bad password.
                with hash_slot(settings):
                    try:
                        if PasswordHash.recommended().verify(password, account.password_hash):
                            return snapshot.user_id_for(account)
                    except Exception:
                        # Invalid legacy hashes fail closed without allowing the
                        # hash or backend exception to reach an API/log boundary.
                        return None
            elif hmac.compare_digest(
                hashlib.sha256(account.password.encode("utf-8")).digest(),
                hashlib.sha256(password.encode("utf-8")).digest(),
            ):
                return snapshot.user_id_for(account)
            return None
    except CredentialFileError:
        return None
    return None


# Naming aliases keep the startup seam easy to discover for callers while all
# paths still use the same strict parser and complete desired graph.
parse_accounts_file = parse_accounts_markdown
load_account_graph = load_desired_graph
