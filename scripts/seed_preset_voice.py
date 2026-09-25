#!/usr/bin/env python3
"""Insert the shared Eldric Sage preset voice, without calling a provider.

The profile id is stable. Bind Plato by putting that id in
``BASELINE_DEFAULT_VOICES`` as ``plato=<id>``. Running this again is a no-op
when the same row is already present. The supplier voice id is stored
encrypted and is not printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SCRIPT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.modules.voices.preset import (  # noqa: E402
    ELDRIC_SAGE_PROFILE_ID,
    PresetVoiceError,
    ensure_eldricsage_preset,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the Eldric Sage preset voice profile.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--data-root", default=None, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {"maya_env": "operator"}
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if args.data_root is not None:
        overrides["data_root"] = args.data_root
    settings = Settings(_env_file=SCRIPT_ROOT / ".env", **overrides)
    database = Database(settings.database_url, settings.resolved_data_root)
    try:
        database.upgrade_schema()
        with database.session() as session:
            profile_id = ensure_eldricsage_preset(session, settings)
    except (PresetVoiceError, RuntimeError, OSError):
        print("Preset voice seed did not complete.", file=sys.stderr)
        return 1
    finally:
        database.dispose()
    if profile_id != ELDRIC_SAGE_PROFILE_ID:
        print("Preset voice seed did not complete.", file=sys.stderr)
        return 1
    print(f"preset voice profile: {profile_id}")
    print(f"BASELINE_DEFAULT_VOICES=plato={profile_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
