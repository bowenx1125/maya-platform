#!/usr/bin/env python3
"""Run one explicit stage of the immutable system fallback pipeline.

The enroll stage creates or reconciles the platform mapping and stops at
preview_ready. The verify stage performs the separate technical TTS check and
promotes an existing mapping to ready. No supplier path, external ID or audio
payload is printed.
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
from app.modules.voices.fallback import (  # noqa: E402
    FallbackEnrollmentError,
    enroll_system_fallback,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enroll the immutable system English fallback.")
    parser.add_argument("--stage", choices=("enroll", "verify"), default="enroll")
    parser.add_argument("--source", required=False, type=Path, help="Operator-provided audio source")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--data-root", default=None, type=Path)
    parser.add_argument(
        "--allow-real",
        action="store_true",
        help="Explicitly permit the configured real voice provider",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    overrides: dict[str, Any] = {"maya_env": "operator"}
    if args.database_url is not None:
        overrides["database_url"] = args.database_url
    if args.data_root is not None:
        overrides["data_root"] = args.data_root
    # ``uv run --directory backend`` changes the process working directory,
    # while the private Demo environment file intentionally lives at the
    # product root. Load that exact ignored file without printing its content.
    settings = Settings(_env_file=SCRIPT_ROOT / ".env", **overrides)
    if args.stage == "enroll" and args.source is None:
        print("System fallback enrollment requires --source.", file=sys.stderr)
        return 1
    try:
        profile_id = enroll_system_fallback(
            settings,
            args.source,
            allow_real=args.allow_real,
            stage=args.stage,
        )
    except (FallbackEnrollmentError, RuntimeError, OSError):
        print(f"System fallback {args.stage} did not complete.", file=sys.stderr)
        return 1
    print(f"System fallback {args.stage} completed: {profile_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
