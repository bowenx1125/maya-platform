from __future__ import annotations

import logging
import sys
from datetime import timedelta
from io import BytesIO
from types import ModuleType, SimpleNamespace
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import app.modules.knowledge.ingest as knowledge_ingest
import app.modules.knowledge.multipart as multipart
import app.modules.knowledge.router as knowledge_router
import app.modules.knowledge.services as knowledge_services
import pytest
from app.core.models import AgentVersionDocument, GroupMember, KnowledgeDocument
from app.modules.knowledge.ingest import (
    KnowledgeImportError,
    convert_knowledge_upload,
)
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)
from sqlalchemy import delete, select
from starlette.requests import Request

from tests.conftest import login

GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _docx_bytes() -> bytes:
    document = Document()
    document.add_heading("Knowledge boundaries", level=1)
    document.add_paragraph("A concept is supported by evidence.")
    document.add_paragraph("Review the source first.", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Term"
    table.cell(0, 1).text = "Meaning"
    table.cell(1, 0).text = "Evidence"
    table.cell(1, 1).text = "A source used to support a claim."
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _pdf_bytes(
    page_texts: list[str | None],
    *,
    non_text_content_pages: set[int] | None = None,
) -> bytes:
    writer = PdfWriter()
    for page_index, text in enumerate(page_texts):
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            if non_text_content_pages and page_index in non_text_content_pages:
                content = DecodedStreamObject()
                content.set_data(b"q Q")
                page[NameObject("/Contents")] = writer._add_object(content)
            continue
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_reference = writer._add_object(font)
        fonts = DictionaryObject({NameObject("/F1"): font_reference})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_docx_conversion_keeps_headings_lists_and_tables() -> None:
    filename, output = convert_knowledge_upload("lesson.docx", _docx_bytes())

    markdown = output.decode("utf-8")
    assert filename == "lesson.docx.md"
    assert "# Knowledge boundaries" in markdown
    assert "- Review the source first." in markdown
    assert "| Term | Meaning |" in markdown
    assert "| Evidence | A source used to support a claim. |" in markdown


def test_pdf_conversion_keeps_physical_page_markers() -> None:
    filename, output = convert_knowledge_upload(
        "lecture.pdf", _pdf_bytes(["First page evidence", "Second page evidence"])
    )

    markdown = output.decode("utf-8")
    assert filename == "lecture.pdf.md"
    assert "## Page 1" in markdown and "First page evidence" in markdown
    assert "## Page 2" in markdown and "Second page evidence" in markdown


def test_pdf_conversion_marks_unreadable_pages_and_rejects_image_only_files() -> None:
    _, markdown_bytes = convert_knowledge_upload("lecture.pdf", _pdf_bytes(["Readable page", None]))
    assert b"No page content was found on this page." in markdown_bytes

    with pytest.raises(KnowledgeImportError, match="pdf_no_text"):
        convert_knowledge_upload("scan.pdf", _pdf_bytes([None]))


def test_pdf_mixed_content_ocr_targets_only_pages_without_selectable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bytes, list[int]]] = []
    limit_events: list[str] = []

    def ocr(data: bytes, page_indexes: list[int]) -> dict[int, str]:
        calls.append((data, page_indexes))
        return {1: "Locally recognized page"}

    monkeypatch.setattr(knowledge_ingest, "_run_pdf_ocr", ocr)
    pdf = _pdf_bytes(["Selectable page", None], non_text_content_pages={1})
    markdown = knowledge_ingest._pdf_to_markdown(
        pdf, before_ocr=lambda: limit_events.append("extended")
    )

    assert calls == [(pdf, [1])]
    assert limit_events == ["extended"]
    assert "Selectable page" in markdown
    assert "> OCR-generated text; teacher review required." in markdown
    assert "Locally recognized page" in markdown


def test_pdf_ocr_without_readable_results_returns_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_ingest, "_run_pdf_ocr", lambda _data, _pages: {})
    pdf = _pdf_bytes([None], non_text_content_pages={0})

    with pytest.raises(KnowledgeImportError, match="pdf_no_text"):
        knowledge_ingest._pdf_to_markdown(pdf)


def test_isolated_document_worker_logs_only_the_safe_failure_code(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class BusySlots:
        def acquire(self, *, timeout: float) -> bool:
            assert timeout == 2
            return False

    monkeypatch.setattr(knowledge_ingest, "_INGEST_WORKER_SLOTS", BusySlots())

    with caplog.at_level(logging.WARNING, logger=knowledge_ingest.__name__):
        with pytest.raises(KnowledgeImportError, match="processing_failed"):
            knowledge_ingest._convert_document_isolated("pdf", b"private upload data")

    assert "reason=processing_failed" in caplog.text
    assert "private upload data" not in caplog.text


def test_pdf_ocr_rasterizes_only_selected_pages_with_bundled_rapidocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered: list[tuple[int, float, bool]] = []
    model_params: dict[str, Any] = {}

    class Bitmap:
        def __init__(self, page_index: int) -> None:
            self.page_index = page_index

        def to_numpy(self) -> int:
            return self.page_index

        def close(self) -> None:
            return None

    class Page:
        def __init__(self, page_index: int) -> None:
            self.page_index = page_index

        def render(self, *, scale: float, limit_image_cache: bool) -> Bitmap:
            rendered.append((self.page_index, scale, limit_image_cache))
            return Bitmap(self.page_index)

        def close(self) -> None:
            return None

    class Document:
        def __init__(self, _data: bytes) -> None:
            pass

        def __enter__(self) -> Document:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def __len__(self) -> int:
            return 4

        def __getitem__(self, page_index: int) -> Page:
            return Page(page_index)

    class Engine:
        def __call__(self, image: int) -> SimpleNamespace:
            return SimpleNamespace(txts=(f"recognized page {image}",))

    def create_engine(*, params: dict[str, Any]) -> Engine:
        model_params.update(params)
        return Engine()

    rapidocr = ModuleType("rapidocr")
    rapidocr.RapidOCR = create_engine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=Document))
    monkeypatch.setitem(sys.modules, "rapidocr", rapidocr)
    monkeypatch.setattr(knowledge_ingest, "_bundled_rapidocr_model_dir", lambda: "models")

    result = knowledge_ingest._run_pdf_ocr(b"private PDF bytes", [1, 3])

    assert result == {1: "recognized page 1", 3: "recognized page 3"}
    assert rendered == [(1, 150 / 72, True), (3, 150 / 72, True)]
    assert model_params["Global.model_root_dir"] == "models"
    assert model_params["EngineConfig.onnxruntime.intra_op_num_threads"] == 2
    assert model_params["EngineConfig.onnxruntime.inter_op_num_threads"] == 1


def test_pdf_ocr_rejects_invalid_page_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    class Document:
        def __init__(self, _data: bytes) -> None:
            pass

        def __enter__(self) -> Document:
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def __len__(self) -> int:
            return 1

    rapidocr = ModuleType("rapidocr")
    rapidocr.RapidOCR = lambda **_kwargs: object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=Document))
    monkeypatch.setitem(sys.modules, "rapidocr", rapidocr)
    monkeypatch.setattr(knowledge_ingest, "_bundled_rapidocr_model_dir", lambda: "models")

    with pytest.raises(KnowledgeImportError, match="processing_failed"):
        knowledge_ingest._run_pdf_ocr(b"private PDF bytes", [1])


def test_pdf_ocr_page_limit_fails_before_running_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_ingest, "MAX_PDF_OCR_PAGES", 1)
    monkeypatch.setattr(
        knowledge_ingest,
        "_run_pdf_ocr",
        lambda _data, _pages: pytest.fail("OCR must not start above the page cap"),
    )
    pdf = _pdf_bytes([None, None], non_text_content_pages={0, 1})

    with pytest.raises(KnowledgeImportError, match="pdf_limit"):
        knowledge_ingest._pdf_to_markdown(pdf)


def test_pdf_ocr_text_keeps_the_extracted_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(knowledge_ingest, "MAX_RAG_CHARS", 64)
    monkeypatch.setattr(
        knowledge_ingest,
        "_run_pdf_ocr",
        lambda _data, _pages: {0: "recognized text " * 8},
    )
    pdf = _pdf_bytes([None], non_text_content_pages={0})

    with pytest.raises(KnowledgeImportError, match="content_too_large"):
        knowledge_ingest._pdf_to_markdown(pdf)


def test_pdf_page_content_stops_when_work_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.knowledge.ingest.MAX_PDF_CONTENT_WORK_BYTES",
        128,
    )
    with pytest.raises(KnowledgeImportError, match="pdf_limit"):
        knowledge_ingest._pdf_to_markdown(_pdf_bytes(["x" * 200]))


def test_pdf_worker_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge_ingest, "INGEST_WORKER_TIMEOUT_SECONDS", 0)
    with pytest.raises(KnowledgeImportError, match="processing_failed"):
        convert_knowledge_upload("lecture.pdf", _pdf_bytes(["Page text"]))


def test_docx_conversion_rejects_bad_and_expanded_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(KnowledgeImportError, match="invalid_docx"):
        convert_knowledge_upload("lesson.docx", b"not a Word document")

    monkeypatch.setattr("app.modules.knowledge.ingest.MAX_DOCX_PART_BYTES", 8)
    expanded = BytesIO()
    with ZipFile(expanded, "w", ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"x" * 9)
    with pytest.raises(KnowledgeImportError, match="docx_limit"):
        convert_knowledge_upload("lesson.docx", expanded.getvalue())


def test_docx_memory_exhaustion_is_reported_as_processing_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_memory_error(_data: bytes) -> Document:
        raise MemoryError

    monkeypatch.setattr(knowledge_ingest, "load_docx", raise_memory_error)
    with pytest.raises(KnowledgeImportError, match="processing_failed"):
        knowledge_ingest._docx_to_markdown(_docx_bytes())


def test_upload_format_and_file_size_are_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(KnowledgeImportError, match="unsupported_format"):
        convert_knowledge_upload("lesson.doc", b"legacy Word")

    monkeypatch.setattr("app.modules.knowledge.ingest.MAX_UPLOAD_FILE_BYTES", 4)
    with pytest.raises(KnowledgeImportError, match="upload_size"):
        convert_knowledge_upload("notes.md", b"12345")


@pytest.mark.asyncio
async def test_multipart_stream_rejects_chunked_body_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(multipart, "MAX_UPLOAD_REQUEST_BYTES", 8)
    chunks = [b"12345", b"67890"]

    async def receive() -> dict[str, Any]:
        if chunks:
            chunk = chunks.pop(0)
            return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        },
        receive,
    )
    with pytest.raises(ValueError, match="too large"):
        await multipart.parse_upload(request)


def test_teacher_can_add_courseware_to_group_library_without_binding_it_to_draft(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, student_csrf = login(client, "bowen")
        created = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": student_csrf,
                "Idempotency-Key": "create-courseware-agent",
            },
            json={"name": "Courseware Agent"},
        )
        assert created.status_code == 201, created.text
        version_id = created.json()["versions"][0]["id"]
        student_upload = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": student_csrf,
                "Idempotency-Key": "student-source-upload",
            },
            files={"file": ("student.md", b"# Student notes", "text/markdown")},
        )
        assert student_upload.status_code == 201, student_upload.text
        student_document_id = student_upload.json()["document"]["id"]

        _teacher, teacher_csrf = login(client, "maya")
        monkeypatch.setattr(
            knowledge_router,
            "scoped_group_role",
            lambda _db, _context, _group_id: "student",
        )
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": "upload-courseware-docx",
        }
        uploaded = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=headers,
            files={
                "file": (
                    "lesson.docx",
                    _docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()["document"]
        assert document["source_filename"] == "lesson.docx.md"
        assert document["source_owner_role"] == "teacher"
        teacher_library = client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents")
        assert teacher_library.status_code == 200
        assert {item["id"] for item in teacher_library.json()} == {
            document["id"],
            student_document_id,
        }
        downloaded = client.get(f"/api/v1/knowledge-documents/{document['id']}/download")
        assert downloaded.status_code == 200
        assert b"# Knowledge boundaries" in downloaded.content

        bound = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers={**headers, "Idempotency-Key": "teacher-cannot-bind-file"},
            data={"target_agent_version_id": version_id, "expected_revision": "0"},
            files={
                "file": (
                    "lesson.docx",
                    _docx_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert bound.status_code == 404
        _student_again, student_csrf_again = login(client, "bowen")
        replaced = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/replace",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": student_csrf_again,
                "Idempotency-Key": "student-replace-teacher-source",
            },
            data={
                "expected_content_hash": document["content_hash"],
                "expected_index_revision": str(document["index_revision"]),
            },
            files={"file": ("replace.md", b"# Changed", "text/markdown")},
        )
        assert replaced.status_code == 404
        student_reindex = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/reindex",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": student_csrf_again,
                "Idempotency-Key": "student-reindex-teacher-source",
            },
        )
        assert student_reindex.status_code == 404
        student_library = client.get(f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents")
        assert student_library.status_code == 200
        assert {item["id"] for item in student_library.json()} == {
            document["id"],
            student_document_id,
        }
        with database.session() as session:
            stored = session.get(KnowledgeDocument, document["id"])
            assert stored is not None and stored.workspace_state == "active"
            assert stored.source_owner_role == "teacher"
            assert (
                session.scalar(
                    select(AgentVersionDocument.agent_version_id).where(
                        AgentVersionDocument.document_id == document["id"]
                    )
                )
                is None
            )

        with database.session() as session:
            teacher_document = session.get(KnowledgeDocument, document["id"])
            assert teacher_document is not None
            teacher_document.index_status = "failed"
            session.commit()
        _teacher_again, teacher_csrf_again = login(client, "maya")
        teacher_reindex = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/reindex",
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": teacher_csrf_again,
                "Idempotency-Key": "teacher-reindex-courseware",
            },
        )
        assert teacher_reindex.status_code == 202, teacher_reindex.text


def test_upload_and_replace_keep_idempotency_claim_during_slow_conversion(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _database, _settings = app_factory()
    now = knowledge_services.now_utc
    elapsed = timedelta(0)

    def advanced_now() -> Any:
        return now() + elapsed

    original_convert = knowledge_router.convert_knowledge_upload

    def slow_conversion(filename: str, content: bytes) -> tuple[str, bytes]:
        nonlocal elapsed
        if filename.endswith(".docx"):
            elapsed += timedelta(seconds=11)
        return original_convert(filename, content)

    monkeypatch.setattr(knowledge_services, "now_utc", advanced_now)
    monkeypatch.setattr(knowledge_router, "convert_knowledge_upload", slow_conversion)
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, csrf = login(client, "bowen")
        headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
        uploaded = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers={**headers, "Idempotency-Key": "slow-docx-courseware-upload"},
            files={"file": ("lesson.docx", _docx_bytes(), "application/octet-stream")},
        )
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()["document"]

        replaced = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/replace",
            headers={**headers, "Idempotency-Key": "slow-docx-courseware-replace"},
            data={
                "expected_content_hash": document["content_hash"],
                "expected_index_revision": str(document["index_revision"]),
            },
            files={"file": ("lesson.docx", _docx_bytes(), "application/octet-stream")},
        )
        assert replaced.status_code == 201, replaced.text


def test_upload_idempotent_replay_skips_file_conversion(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _database, _settings = app_factory()
    conversions = 0

    def convert(filename: str, content: bytes) -> tuple[str, bytes]:
        nonlocal conversions
        conversions += 1
        return filename, content

    monkeypatch.setattr(knowledge_router, "convert_knowledge_upload", convert)
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, csrf = login(client, "bowen")
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "knowledge-replay-same-file",
        }
        payload = {"file": ("lesson.md", b"# Idempotent", "text/markdown")}
        first = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=headers,
            files=payload,
        )
        second = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=headers,
            files=payload,
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json() == second.json()
    assert conversions == 1


def test_unjoined_teacher_can_read_own_courseware_without_group_access(
    app_factory: Any,
) -> None:
    app, _database, _settings = app_factory()
    documents_url = f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents"
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, student_csrf = login(client, "bowen")
        student_document = client.post(
            documents_url,
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": student_csrf,
                "Idempotency-Key": "student-courseware-gate",
            },
            files={"file": ("student.md", b"# Student notes", "text/markdown")},
        )
        assert student_document.status_code == 201, student_document.text

        _teacher, teacher_csrf = login(client, "maya")
        assert client.get(documents_url).status_code == 404
        courseware = client.post(
            documents_url,
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": teacher_csrf,
                "Idempotency-Key": "teacher-courseware-own",
            },
            files={"file": ("lesson.md", b"# Teacher courseware", "text/markdown")},
        )
        assert courseware.status_code == 201, courseware.text

        listing = client.get(documents_url)
        assert listing.status_code == 200, listing.text
        assert [item["id"] for item in listing.json()] == [courseware.json()["document"]["id"]]
        assert [item["source_owner_role"] for item in listing.json()] == ["teacher"]


def test_upload_reports_distinct_format_text_size_and_metadata_errors(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _database, _settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        _student, csrf = login(client, "bowen")
        headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}

        def upload(name: str, content: bytes, key: str, **data: str) -> Any:
            return client.post(
                f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
                headers={**headers, "Idempotency-Key": key},
                data=data,
                files={"file": (name, content, "application/octet-stream")},
            )

        unsupported = upload("lesson.txt", b"text", "unsupported-format-key")
        assert unsupported.status_code == 422
        assert unsupported.json()["code"] == "knowledge_import_unsupported"

        no_text = upload("scan.pdf", _pdf_bytes([None]), "no-selectable-text-key")
        assert no_text.status_code == 422
        assert no_text.json()["code"] == "knowledge_import_no_text"

        invalid_metadata = upload(
            "notes.md",
            b"# Notes",
            "invalid-target-version-key",
            target_agent_version_id="not-a-uuid",
        )
        assert invalid_metadata.status_code == 422
        assert invalid_metadata.json()["code"] == "invalid_request"

        monkeypatch.setattr(knowledge_ingest, "MAX_DOCX_PART_BYTES", 1)
        expanded_docx = upload("lesson.docx", _docx_bytes(), "too-large-docx-key")
        assert expanded_docx.status_code == 422
        assert expanded_docx.json()["code"] == "knowledge_import_too_large"

        def reject_unsafe_pdf(filename: str, content: bytes) -> tuple[str, bytes]:
            raise KnowledgeImportError("processing_failed")

        monkeypatch.setattr(knowledge_router, "convert_knowledge_upload", reject_unsafe_pdf)
        processing_failed = upload("lesson.pdf", b"%PDF-1.7", "pdf-worker-limit-key")
        assert processing_failed.status_code == 422
        assert processing_failed.json()["code"] == "knowledge_import_processing_failed"

        monkeypatch.setattr(multipart, "MAX_UPLOAD_FILE_BYTES", 1)
        too_large = upload("notes.md", b"# Notes", "too-large-upload-key")
        assert too_large.status_code == 422
        assert too_large.json()["code"] == "knowledge_import_too_large"


def test_replacement_rechecks_workspace_membership_after_conversion(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app, raise_server_exceptions=False) as client:
        student, csrf = login(client, "bowen")
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "membership-recheck-upload",
        }
        created = client.post(
            f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
            headers=headers,
            files={"file": ("notes.md", b"# Original", "text/markdown")},
        )
        assert created.status_code == 201, created.text
        document = created.json()["document"]

        def revoke_then_convert(filename: str, content: bytes) -> tuple[str, bytes]:
            with database.session() as session:
                session.execute(
                    delete(GroupMember).where(
                        GroupMember.group_id == GROUP_DEMO_ID,
                        GroupMember.user_id == student["user"]["id"],
                    )
                )
                session.commit()
            return filename, content

        monkeypatch.setattr(knowledge_router, "convert_knowledge_upload", revoke_then_convert)
        replaced = client.post(
            f"/api/v1/knowledge-documents/{document['id']}/replace",
            headers={**headers, "Idempotency-Key": "membership-recheck-replace"},
            data={
                "expected_content_hash": document["content_hash"],
                "expected_index_revision": str(document["index_revision"]),
            },
            files={"file": ("updated.md", b"# Replacement", "text/markdown")},
        )
        assert replaced.status_code == 404

        with database.session() as session:
            current = session.get(KnowledgeDocument, document["id"])
            assert current is not None
            assert current.workspace_state == "active"
            assert current.content_hash == document["content_hash"]
