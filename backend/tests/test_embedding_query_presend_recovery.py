import pytest

from app.modules.debates.generation.retrieval import TurnSubquery
from app.modules.debates.playback import generation_adapter as ga
from app.modules.knowledge.providers.packing import MAX_BATCH_TOKENS
from app.modules.knowledge.providers.tokenizer import count_tokens


def test_oversized_subqueries_are_clipped_to_fit_one_batch():
    huge = "辩论观点证据。" * 20000
    items = (TurnSubquery("viewpoint", huge), TurnSubquery("rebuttal", "short query"))
    fitted = ga._fit_subqueries_to_embedding_batch(items)
    assert fitted[1] is items[1]
    assert fitted[0].query_kind == "viewpoint"
    assert huge.startswith(fitted[0].text)
    total = sum(count_tokens(item.text) for item in fitted)
    assert total <= MAX_BATCH_TOKENS
    assert all(count_tokens(item.text) <= ga._MAX_SUBQUERY_TOKENS for item in fitted)


def test_small_subqueries_unchanged():
    items = (TurnSubquery("viewpoint", "topic\nposition"),)
    assert ga._fit_subqueries_to_embedding_batch(items) == items


def test_presend_codes_are_local_plan_errors_only():
    assert "embedding_batch_tokens_exceeded" in ga._PRESEND_EMBEDDING_PLAN_CODES
    assert "acceptance_unknown" not in ga._PRESEND_EMBEDDING_PLAN_CODES
    assert "provider_not_sent" not in ga._PRESEND_EMBEDDING_PLAN_CODES


def test_prior_attempts_allow_presend_plan_failure():
    """A failed local plan row must not consume the not_sent retry slot."""
    from types import SimpleNamespace

    from app.modules.knowledge.providers.sql_query import (
        PRESEND_EMBEDDING_PLAN_CODES,
        SqlAlchemyQueryControlAdapter,
        SqlQueryBudgetError,
    )

    assert ga._PRESEND_EMBEDDING_PLAN_CODES == PRESEND_EMBEDDING_PLAN_CODES

    class _Gate:
        request = SimpleNamespace(attempt_no=2)
        _check_prior_attempts = SqlAlchemyQueryControlAdapter._check_prior_attempts

    gate = _Gate()
    gate._check_prior_attempts(
        (
            SimpleNamespace(
                attempt_no=1,
                state="failed",
                safe_error_code="embedding_batch_tokens_exceeded",
            ),
        )
    )
    gate._check_prior_attempts(
        (SimpleNamespace(attempt_no=1, state="not_sent", safe_error_code="provider_not_sent"),)
    )
    with pytest.raises(SqlQueryBudgetError) as blocked:
        gate._check_prior_attempts(
            (
                SimpleNamespace(
                    attempt_no=1,
                    state="failed",
                    safe_error_code="acceptance_unknown",
                ),
            )
        )
    assert blocked.value.code == "embedding_query_retry_forbidden"
