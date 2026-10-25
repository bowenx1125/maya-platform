"""scripts/cleanup_soft_deleted.py: legacy soft-deleted Debates go, live ones stay."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.debates.models import Debate
from fastapi.testclient import TestClient

from tests.test_course_live_push import _debate

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_soft_deleted.py"


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("cleanup_soft_deleted", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_soft_deleted_debate_is_removed_and_live_debates_are_not(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    script = _script()
    gone = _debate(database)
    kept = _debate(database)
    with database.session() as db:
        db.get(Debate, gone).deleted_at = datetime.now(UTC)
    with database.session() as db:
        before = script.counts(db, settings.resolved_data_root)
        live_before = script.live_debate_counts(db)
    assert before["deleted_debates"] == 1

    assert script.delete_legacy_debates(database, settings.resolved_data_root) == (1, 0)

    with database.session() as db:
        assert db.get(Debate, gone) is None
        assert db.get(Debate, kept) is not None
        assert script.counts(db, settings.resolved_data_root)["deleted_debates"] == 0
        assert script.live_debate_counts(db) == live_before


def test_apply_runs_every_phase_and_keeps_live_debates(
    app_bundle: Any, client: TestClient, capsys: Any
) -> None:
    _app, database, settings = app_bundle
    script = _script()
    gone = _debate(database)
    kept = _debate(database)
    with database.session() as db:
        db.get(Debate, gone).deleted_at = datetime.now(UTC)
    args = [
        "--database-url",
        settings.database_url,
        "--data-root",
        str(settings.resolved_data_root),
    ]
    assert script.main(args) == 0  # dry-run writes nothing
    with database.session() as db:
        assert db.get(Debate, gone) is not None
    assert script.main([*args, "--apply"]) == 0
    assert "legacy debates removed 1 failed 0" in capsys.readouterr().out
    with database.session() as db:
        assert db.get(Debate, gone) is None
        assert db.get(Debate, kept) is not None
