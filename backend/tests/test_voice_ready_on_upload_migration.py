"""0073 promotes cleanly enrolled preview-ready voices to ready, nothing else."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.core.db import Database
from sqlalchemy import text

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _config(database_url: str) -> Config:
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["database_url"] = database_url
    return config


ROWS = {
    # id: (scope, status, safe_error_code, expected status after 0073)
    "v-group-clean": ("group", "preview_ready", None, "ready"),
    "v-personal-clean": ("personal", "preview_ready", None, "ready"),
    "v-group-tts-error": ("group", "preview_ready", "tts_response_invalid", "preview_ready"),
    "v-system-fallback": ("system", "preview_ready", None, "preview_ready"),
    "v-group-failed": ("group", "failed", "voice_enrollment_failed", "failed"),
    "v-group-enrolling": ("group", "enrolling", None, "enrolling"),
    "v-group-deleted": ("group", "deleted", None, "deleted"),
    "v-group-ready": ("group", "ready", None, "ready"),
}


def test_0073_promotes_only_clean_student_and_teacher_previews(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'voice-ready.sqlite3'}"
    config = _config(database_url)
    command.upgrade(config, "0072_attempt_teacher_hidden")
    # Raw sqlite3 leaves foreign keys off, so group rows need no seeded group.
    now = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(tmp_path / "voice-ready.sqlite3")) as raw, raw:
        for profile_id, (scope, status, error, _expected) in ROWS.items():
            raw.execute(
                "INSERT INTO voice_profiles (id, scope, group_id, display_name, status, "
                "provider_key, target_model_key, recovery_name, provenance_json, "
                "safe_error_code, created_at, updated_at) "
                "VALUES (?, ?, ?, 'Voice', ?, 'mock', 'mock-model', ?, '{}', ?, ?, ?)",
                (
                    profile_id,
                    scope,
                    GROUP_ID if scope == "group" else None,
                    status,
                    f"recovery-{profile_id}",
                    error,
                    now,
                    now,
                ),
            )

    command.upgrade(config, "0073_voice_ready_on_upload")

    database = Database(database_url, tmp_path)
    with database.engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT id, status FROM voice_profiles")).all())
    assert rows == {profile_id: row[3] for profile_id, row in ROWS.items()}

    # Downgrade keeps every row and status: no voice is deleted or demoted.
    database.dispose()
    command.downgrade(config, "0072_attempt_teacher_hidden")
    with database.engine.connect() as connection:
        after = dict(connection.execute(text("SELECT id, status FROM voice_profiles")).all())
    assert after == rows
    database.dispose()
