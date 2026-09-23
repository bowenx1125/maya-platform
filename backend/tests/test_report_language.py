from app.modules.reports.real_prompt import build_report_request
from app.modules.reports.real_schema import validate_report_sections
from app.modules.reports.schemas import ReportSectionOutput
from app.modules.reports.service import (
    build_real_report_request,
    generate_mock_report,
    render_real_report_markdown,
    validate_report_markdown,
)
from app.providers.llm_adapter import DashScopeLLMConfig

from tests.test_next_wave_report_support import _context, _Tokenizer


def test_chinese_report_language_is_frozen_in_prompt_and_rendered_headings():
    context = _context()
    context.debate.output_language = "zh"
    request = build_real_report_request(context)
    assert request.canonical_payload()["source_language"] == "zh"
    wire = build_report_request(
        request,
        config=DashScopeLLMConfig(api_key="fixture", workspace_id="fixture-workspace"),
        tokenizer=_Tokenizer(),
    )
    assert "六个JSON字段的正文全部使用中文" in wire.system_message.content
    assert "English prose only" not in wire.system_message.content
    sections = ReportSectionOutput(
        **{
            key: "根据RAG资料，双方保留分歧，并说明证据的适用边界。"
            for key in ReportSectionOutput.model_fields
        }
    )
    assert validate_report_sections(sections) == sections
    markdown = render_real_report_markdown(context, sections)
    assert markdown.startswith("# 文明互鉴报告")
    assert "## 课堂观点" in markdown
    assert "Classroom totals" not in markdown
    validate_report_markdown(
        markdown,
        manifest=context.manifest,
        vote_total=context.vote_total,
        barrage_total=context.barrage_total,
    )


def test_report_content_requirements_never_reject_an_otherwise_valid_shape():
    sections = {key: "S2。**保留原文** " * 1000 for key in ReportSectionOutput.model_fields}
    assert validate_report_sections(sections).model_dump() == sections


def test_mock_report_uses_chinese_for_chinese_debate():
    context = _context()
    context.debate.output_language = "zh"
    markdown, _ = generate_mock_report(context)
    assert markdown.startswith("# 文明互鉴报告")
    assert "这是Mock报告" in markdown
    assert "The debate considered" not in markdown
