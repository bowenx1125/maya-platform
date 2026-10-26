"""Snapshot publication always auto-confirms, whatever the standing-consent flags say."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.models import Agent, AgentVersion
from app.modules.agents.router import _publish_real_embedding_snapshot
from app.modules.knowledge.providers.product_publication import (
    ensure_real_embedding_export_manifest,
    prepare_real_snapshot_build,
)
from app.providers.control_repository import ProviderRepository

from tests.test_wave4_embedding_product_publication import (
    _CountingRealProvider,
    _make_fixture,
    _policy,
)


def _settings(fixture, policy, *, standing: bool) -> SimpleNamespace:
    return SimpleNamespace(
        demo_mode=True,
        demo_auto_confirm_provider=standing,
        provider_standing_consent=standing,
        embedding_provider="dashscope",
        provider_policy_hash_for=lambda _kind: policy.policy_hash,
        resolved_data_root=fixture.data_root,
    )


@pytest.mark.parametrize("standing", [True, False])
def test_snapshot_publish_applies_standing_consent_then_rechecks_owner(
    tmp_path, monkeypatch: pytest.MonkeyPatch, standing: bool
) -> None:
    fixture = _make_fixture(tmp_path)
    policy = _policy()
    ProviderRepository(fixture.database).save_policy_snapshot(policy, snapshot_id=str(uuid4()))
    with fixture.database.session() as db:
        version = db.get(AgentVersion, fixture.agent_version_id)
        assert version is not None
        agent = db.get(Agent, version.agent_id)
        assert version is not None and agent is not None

    checks: list[dict[str, object]] = []
    import app.modules.agents.router as router

    original_require = router.require_exact_confirmation

    def observe_require(*args: object, **kwargs: object) -> object:
        checks.append(dict(kwargs))
        return original_require(*args, **kwargs)

    provider = _CountingRealProvider()
    monkeypatch.setattr(router, "require_exact_confirmation", observe_require)
    monkeypatch.setattr(router, "select_embedding_provider", lambda _settings: provider)
    monkeypatch.setattr(router, "renew_idempotency_lease", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        router,
        "run_confirmed_real_embedding_publication",
        lambda *_args, **_kwargs: SimpleNamespace(status="succeeded", safe_error_code=None),
    )
    try:
        with fixture.database.session() as db:
            _publish_real_embedding_snapshot(
                db,
                _settings(fixture, policy, standing=standing),
                version=version,
                agent=agent,
                expected_revision=1,
                record=SimpleNamespace(id=str(uuid4()), claim_token="claim"),
            )
        assert len(checks) == 2
        assert all(
            item
            == {
                "course_id": fixture.course_id,
                "group_id": fixture.group_id,
                "agent_version_id": fixture.agent_version_id,
            }
            for item in checks
        )
        with fixture.database.session() as db:
            build = prepare_real_snapshot_build(
                db,
                fixture.data_root,
                course_id=fixture.course_id,
                group_id=fixture.group_id,
                agent_version_id=fixture.agent_version_id,
                expected_revision=1,
            )
            manifest = ensure_real_embedding_export_manifest(
                db,
                build,
                course_id=fixture.course_id,
                group_id=fixture.group_id,
                agent_version_id=fixture.agent_version_id,
                policy=policy,
            )
            assert (
                ProviderRepository(fixture.database).get_export_confirmation(manifest.manifest_hash)
                is not None
            )
    finally:
        fixture.database.dispose()
