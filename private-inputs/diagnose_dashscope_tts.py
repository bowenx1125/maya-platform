#!/usr/bin/env python3
"""Operator-only Maya DashScope TTS Gate driver.

The default mode is a local, no-network configuration check.  A real call is
reachable only with both ``--allow-real`` and ``--confirm-one-real-call``;
the second flag is deliberately separate so a copied command cannot
accidentally spend a provider request.  This script never writes ``.env`` and
never prints credentials, supplier voice IDs, URLs, response bodies, audio
bytes, or local paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "maya-platform" / "backend"
DEFAULT_ENV_FILE = BACKEND_ROOT.parent / ".env"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.db import Database  # noqa: E402
from app.modules.voices.tts_diagnostic import (  # noqa: E402
    TTSGateError,
    run_operator_tts_gate,
)


def _settings(env_file: Path) -> Settings:
    try:
        return Settings(_env_file=env_file, maya_env="operator")
    except Exception as exc:
        del exc
        raise SystemExit("[FAIL] Operator configuration could not be loaded.") from None


def _check_configuration(settings: Settings) -> None:
    if settings.tts_provider != "dashscope":
        raise SystemExit("[FAIL] TTS selector is not dashscope.")
    if settings.voice_provider != "mock":
        raise SystemExit("[FAIL] Voice selector must remain mock.")
    if settings.llm_provider != "mock" or settings.embedding_provider != "mock":
        raise SystemExit("[FAIL] LLM and embedding selectors must remain mock.")
    if settings.translation_provider not in {None, "", "mock"}:
        raise SystemExit("[FAIL] Translation selector must remain disabled or mock.")
    if not settings.dashscope_api_key or not settings.dashscope_workspace_id:
        raise SystemExit("[FAIL] DashScope credentials are incomplete (values hidden).")
    if settings.dashscope_region != "cn-beijing":
        raise SystemExit("[FAIL] DashScope region must be cn-beijing.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Maya's one-shot operator TTS Gate.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--check-only", action="store_true", help="Never open the database.")
    parser.add_argument(
        "--allow-real",
        action="store_true",
        help="Arm the real DashScope branch; still requires the confirmation flag.",
    )
    parser.add_argument(
        "--confirm-one-real-call",
        action="store_true",
        help="Confirm that this invocation may issue the single attempt-3 TTS request.",
    )
    args = parser.parse_args()

    settings = _settings(args.env_file.expanduser().resolve())
    try:
        _check_configuration(settings)
    except SystemExit:
        raise
    except Exception:
        raise SystemExit("[FAIL] Operator configuration is not permitted.") from None
    print("[OK] DashScope TTS selector and Mock-only companion selectors are configured.")
    print("[OK] Beijing region and required credentials are present (values hidden).")

    if args.check_only or not args.allow_real:
        print("[OK] No database or network operation was performed.")
        return 0
    if not args.confirm_one_real_call:
        raise SystemExit("[FAIL] Add --confirm-one-real-call only after main-window release.")

    database = Database(settings.database_url, settings.resolved_data_root)
    try:
        # Deployment owns the schema; this is a read/upgrade check and never
        # changes .env or any provider-side resource.
        database.upgrade_schema()
        result = run_operator_tts_gate(settings, allow_real=True, database=database)
    except TTSGateError as exc:
        print(f"[RESULT] status=error safe_code={exc.safe_code}")
        return 3
    except Exception:
        print("[RESULT] status=error safe_code=tts_response_invalid")
        return 3
    finally:
        database.dispose()

    print(f"[RESULT] status={result.status} attempt={result.attempt}")
    if result.error_code:
        print(f"[RESULT] safe_code={result.error_code}")
    if result.preview_id:
        # This opaque platform ID is the only success artifact needed by the
        # main window for its authenticated same-origin media check.
        print(f"[RESULT] preview_id={result.preview_id}")
    return 0 if result.status == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
