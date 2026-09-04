"""Point an existing Demo at this machine's current classroom-LAN address.

A router hands out a new lease and the classroom link stops working: every
mutation fails the CSRF origin check, and the QR code points at an address
nobody is listening on. The cause is invisible from the browser -- the page
says only that the form expired -- and the repair was to find the stale line in
an ignored file, edit it, and remember that ``docker compose start`` does not
re-read ``.env``.

The origin check itself is deliberately strict: it trusts the configured
gateway origin and loopback, and nothing else. Widening it so any private
address is accepted would remove this chore by removing the control, and
``_websocket_origin_allowed`` says plainly why that must not happen. So this
re-detects the address instead, rewrites the one line, and tells the operator
to bring the stack back up so the new value is actually read.

    python scripts/refresh_classroom_address.py

Nothing else in ``.env`` is touched, and the file is never created here: a Demo
that has not been bootstrapped is a different problem with a different script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bootstrap_local_demo import detect_private_lan_origin

SETTING = "CLASSROOM_PUBLIC_BASE_URL"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="the Demo .env to update (default: the repository's own)",
    )
    return parser


def rewrite(env_path: Path, origin: str) -> tuple[str | None, bool]:
    """Replace the classroom origin line. Returns the old value and whether it moved."""

    lines = env_path.read_text(encoding="utf-8").splitlines()
    previous: str | None = None
    changed = False
    for index, line in enumerate(lines):
        if not line.startswith(f"{SETTING}="):
            continue
        previous = line.split("=", 1)[1]
        if previous != origin:
            lines[index] = f"{SETTING}={origin}"
            changed = True
        break
    else:
        lines.append(f"{SETTING}={origin}")
        changed = True
    if changed:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return previous, changed


def main() -> int:
    args = _parser().parse_args()
    env_path: Path = args.env
    if not env_path.is_file():
        print(f"No {env_path} to update. Bootstrap the Demo first.", file=sys.stderr)
        return 1
    origin = detect_private_lan_origin()
    if not origin:
        print(
            "No classroom LAN address found on this machine. Connect to the "
            f"classroom network, or set {SETTING} by hand.",
            file=sys.stderr,
        )
        return 1
    previous, changed = rewrite(env_path, origin)
    if not changed:
        print(f"{SETTING} is already {origin}.")
        return 0
    print(f"{SETTING}: {previous or '(unset)'} -> {origin}")
    # Compose reads .env when it creates a container, not when it starts one,
    # so "start" would leave the old value in place and look like this script
    # did nothing.
    print("Run `docker compose up -d` for the new address to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
