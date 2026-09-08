"""Background contributes to frozen generation and retrieval without topic script gates."""

from dataclasses import replace

import pytest
from app.modules.debates.generation.retrieval import build_turn_subqueries
from app.modules.debates.generation.segments import build_segment_input
from app.modules.debates.topic_language import model_topic, normalize_model_text, validate_topic

from tests.test_four_round_content import context


@pytest.mark.parametrize("value", ["中文🙂", "Arabic العربية", "C++ != C#", "123?!", "a\nb\t c"])
def test_any_topic_script_or_symbol_is_independent_of_output_language(value):
    assert validate_topic(value, "en") == value
    assert validate_topic(value, "zh") == value


def test_normalization_keeps_meaningful_spacing_and_symbols():
    assert normalize_model_text("  A\t\nB\u200b + C?\u202e ") == "A B + C?"
    assert model_topic("  A\nB? ") == "A B?"


@pytest.mark.parametrize("round_no", [1, 2, 3, 4])
def test_background_enters_each_frozen_turn_and_retrieval(round_no):
    ctx = replace(context(round_no), topic=model_topic("Water?", "A drought has lasted two weeks."))
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    assert snapshot.to_user_payload()["topic"] == ctx.topic
    queries = build_turn_subqueries(ctx)
    assert any("A drought has lasted two weeks." in query.text for query in queries)


def test_report_accepts_background_beyond_old_title_limit():
    from app.modules.reports.real_schema import ReportRequest

    from tests.test_real_report_prompt import _raw_request

    raw = _raw_request()
    raw["topic"] = model_topic("Water?", "A relevant detail. " * 80)
    report = ReportRequest.model_validate(raw)
    assert report.topic == raw["topic"]
    assert len(report.topic) > 1200
