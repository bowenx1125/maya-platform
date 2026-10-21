import pytest

from app.core.errors import PlatformError
from app.modules.knowledge.markdown import MarkdownInputError, normalize_markdown
from app.modules.knowledge.router import _raise_knowledge_import_failure


def test_normalize_markdown_rejects_c0_control_chars() -> None:
    with pytest.raises(MarkdownInputError, match="^invalid_control_chars$"):
        normalize_markdown("lesson.md", b"# title\x00\x01\x02\n")


def test_normalize_markdown_allows_newlines_and_tabs() -> None:
    document = normalize_markdown("lesson.md", b"# title\n\tbody\n")

    assert document.normalized == "# title\n\tbody\n"


def test_normalize_markdown_converts_crlf_before_control_validation() -> None:
    document = normalize_markdown("lesson.md", b"# title\r\n\tbody\r\n")

    assert document.normalized == "# title\n\tbody\n"


@pytest.mark.parametrize(
    "reason",
    ["invalid", "invalid_filename", "invalid_utf8", "empty_markdown", "invalid_control_chars"],
)
def test_markdown_import_failure_uses_markdown_copy(reason: str) -> None:
    with pytest.raises(PlatformError) as raised:
        _raise_knowledge_import_failure(reason)

    assert raised.value.status_code == 422
    assert raised.value.code == "knowledge_import_invalid"
    assert raised.value.details["reason"] == reason
    message = raised.value.message.casefold()
    assert "markdown" in message
    assert "pdf" not in message
    assert "word" not in message


@pytest.mark.parametrize("reason", ["invalid_pdf", "invalid_docx"])
def test_invalid_document_import_copy_still_mentions_pdf_word(reason: str) -> None:
    with pytest.raises(PlatformError) as raised:
        _raise_knowledge_import_failure(reason)

    assert raised.value.status_code == 422
    assert raised.value.code == "knowledge_import_invalid"
    assert "pdf" in raised.value.message.casefold()
    assert "word" in raised.value.message.casefold()
