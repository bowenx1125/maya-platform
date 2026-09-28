"""Local, bounded text extraction for teacher knowledge uploads."""

from __future__ import annotations

import ctypes
import importlib
import multiprocessing
import os
import re
import threading
import unicodedata
import zipfile
from io import BytesIO
from multiprocessing.process import BaseProcess
from typing import Any, Literal

from docx import Document as load_docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from app.modules.knowledge.markdown import MAX_RAG_CHARS
from app.modules.knowledge.multipart import MAX_UPLOAD_FILE_BYTES

MAX_PDF_PAGES = 200
MAX_DOCX_PARTS = 1024
MAX_DOCX_PART_BYTES = 20 * 1024 * 1024
MAX_DOCX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_PDF_STREAM_BYTES = 2 * 1024 * 1024
MAX_PDF_CONTENT_WORK_BYTES = 32 * 1024 * 1024
MAX_PDF_TOTAL_FORM_INVOCATIONS = 64
MAX_PDF_FORM_INVOCATIONS_PER_PAGE = 16
MAX_PDF_RECOVERY_BYTES = 1 * 1024 * 1024
INGEST_WORKER_MEMORY_BYTES = 512 * 1024 * 1024
INGEST_WORKER_CPU_SECONDS = 20
INGEST_WORKER_TIMEOUT_SECONDS = 30
_INGEST_WORKER_SLOTS = threading.BoundedSemaphore(2)
INGEST_VERSION = "local-markdown-v1"


class KnowledgeImportError(ValueError):
    """An uploaded document cannot be safely converted to Markdown."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _set_ingest_worker_limits() -> None:
    if os.name == "nt":
        return
    try:
        resource: Any = importlib.import_module("resource")

        address_space_limit = getattr(resource, "RLIMIT_AS", None)
        cpu_limit = getattr(resource, "RLIMIT_CPU", None)
        if address_space_limit is None or cpu_limit is None:
            raise RuntimeError("Process resource limits are unavailable")
        resource.setrlimit(
            address_space_limit,
            (INGEST_WORKER_MEMORY_BYTES, INGEST_WORKER_MEMORY_BYTES),
        )
        resource.setrlimit(
            cpu_limit,
            (INGEST_WORKER_CPU_SECONDS, INGEST_WORKER_CPU_SECONDS + 1),
        )
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError("Document worker limits are unavailable") from exc


def _assign_windows_ingest_worker_job(process: BaseProcess) -> int | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    limits = ExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = 0x0002 | 0x0008 | 0x0100 | 0x2000
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.BasicLimitInformation.PerProcessUserTimeLimit = INGEST_WORKER_CPU_SECONDS * 10_000_000
    limits.ProcessMemoryLimit = INGEST_WORKER_MEMORY_BYTES
    worker_handle = kernel32.OpenProcess(0x0001 | 0x0100, False, process.pid)
    if not worker_handle:
        kernel32.CloseHandle(job)
        raise OSError(ctypes.get_last_error(), "OpenProcess for PDF worker failed")
    try:
        configured = kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
        assigned = configured and kernel32.AssignProcessToJobObject(job, worker_handle)
        if not assigned:
            raise OSError(ctypes.get_last_error(), "PDF worker job limits failed")
    except Exception:
        kernel32.CloseHandle(job)
        raise
    finally:
        kernel32.CloseHandle(worker_handle)
    return int(job)


def _ingest_worker(
    kind: Literal["pdf", "docx"],
    send_connection: Any,
    ready_event: Any,
    start_event: Any,
    data: bytes,
) -> None:
    try:
        try:
            _set_ingest_worker_limits()
        except Exception:
            send_connection.send(("error", "processing_failed"))
            return
        ready_event.set()
        if not start_event.wait(timeout=5):
            send_connection.send(("error", "processing_failed"))
            return
        if kind == "pdf":
            markdown = _pdf_to_markdown(data)
        else:
            markdown = _docx_to_markdown(data)
        send_connection.send(("ok", markdown.encode("utf-8")))
    except KnowledgeImportError as exc:
        send_connection.send(("error", exc.reason))
    except MemoryError:
        send_connection.send(("error", "processing_failed"))
    except Exception:
        send_connection.send(("error", "processing_failed"))
    finally:
        ready_event.set()
        send_connection.close()


def _convert_document_isolated(kind: Literal["pdf", "docx"], data: bytes) -> bytes:
    if not _INGEST_WORKER_SLOTS.acquire(timeout=2):
        raise KnowledgeImportError("processing_failed")
    receive_connection: Any = None
    send_connection: Any = None
    process: BaseProcess | None = None
    process_started = False
    job_handle: int | None = None
    try:
        context = multiprocessing.get_context("spawn")
        receive_connection, send_connection = context.Pipe(duplex=False)
        ready_event = context.Event()
        start_event = context.Event()
        process = context.Process(
            target=_ingest_worker,
            args=(kind, send_connection, ready_event, start_event, data),
        )
        process.start()
        process_started = True
        send_connection.close()
        send_connection = None
        if not ready_event.wait(timeout=5):
            raise KnowledgeImportError("processing_failed")
        if receive_connection.poll(0):
            try:
                status, result = receive_connection.recv()
            except EOFError:
                raise KnowledgeImportError("processing_failed") from None
            if status == "error":
                raise KnowledgeImportError(result)
            raise KnowledgeImportError("processing_failed")
        job_handle = _assign_windows_ingest_worker_job(process)
        start_event.set()
        if not receive_connection.poll(INGEST_WORKER_TIMEOUT_SECONDS):
            raise KnowledgeImportError("processing_failed")
        try:
            status, result = receive_connection.recv()
        except EOFError:
            raise KnowledgeImportError("processing_failed") from None
        if status == "error":
            raise KnowledgeImportError(result)
        if status != "ok" or not isinstance(result, bytes):
            raise KnowledgeImportError("processing_failed")
        return result
    except KnowledgeImportError:
        raise
    except Exception as exc:
        raise KnowledgeImportError("processing_failed") from exc
    finally:
        if process is not None and process_started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
        if job_handle is not None and os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(job_handle)
        if receive_connection is not None:
            receive_connection.close()
        if send_connection is not None:
            send_connection.close()
        _INGEST_WORKER_SLOTS.release()


def _convert_pdf_isolated(data: bytes) -> bytes:
    return _convert_document_isolated("pdf", data)


def _convert_docx_isolated(data: bytes) -> bytes:
    return _convert_document_isolated("docx", data)


def _validate_filename(filename: str) -> None:
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or any(unicodedata.category(char) in {"Cc", "Cf"} for char in filename)
    ):
        raise KnowledgeImportError("invalid_filename")


def _converted_filename(filename: str) -> str:
    return filename + ".md"


def _form_xobjects(page: Any) -> set[str]:
    current = page
    for _ in range(33):
        resources = current.get("/Resources")
        if resources is not None:
            resources = resources.get_object()
            xobjects = resources.get("/XObject")
            if xobjects is None:
                return set()
            xobjects = xobjects.get_object()
            return {
                str(name)
                for name, reference in xobjects.items()
                if reference.get_object().get("/Subtype") == "/Form"
            }
        current = current.get("/Parent")
        if current is None:
            break
        current = current.get_object()
    return set()


def _pdf_to_markdown(data: bytes) -> str:
    if b"%PDF-" not in data[:1024]:
        raise KnowledgeImportError("invalid_pdf")
    try:
        # pypdf has decompression and parser limits. These tighter per-call
        # bounds keep a small compressed upload from expanding without limit.
        with apply_configuration(
            maximum_declared_stream_length=MAX_PDF_STREAM_BYTES,
            array_based_stream_maximum_output_length=MAX_PDF_STREAM_BYTES,
            jbig2_maximum_output_length=MAX_PDF_STREAM_BYTES,
            lzw_maximum_output_length=MAX_PDF_STREAM_BYTES,
            run_length_maximum_output_length=MAX_PDF_STREAM_BYTES,
            zlib_maximum_output_length=MAX_PDF_STREAM_BYTES,
            zlib_maximum_recovery_input_length=MAX_PDF_RECOVERY_BYTES,
            image_maximum_buffer_size=MAX_PDF_STREAM_BYTES,
            page_tree_maximum_entries=MAX_PDF_PAGES + 32,
            page_tree_maximum_depth=32,
            xform_maximum_invocations_per_extraction=500,
        ):
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                raise KnowledgeImportError("pdf_limit")
            pages: list[str] = []
            has_text = False
            total_content_work_bytes = 0
            total_text_chars = 0
            total_form_invocations = 0
            markdown_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                remaining_content_work_bytes = MAX_PDF_CONTENT_WORK_BYTES - total_content_work_bytes
                if remaining_content_work_bytes <= 1:
                    raise KnowledgeImportError("pdf_limit")
                raw_contents = page.get("/Contents")
                if raw_contents is not None:
                    resolved_contents = raw_contents.get_object()
                    content_streams = (
                        resolved_contents
                        if isinstance(resolved_contents, list)
                        else [resolved_contents]
                    )
                    decoded_page_bytes = 0
                    for stream_reference in content_streams:
                        remaining_content_work_bytes = (
                            MAX_PDF_CONTENT_WORK_BYTES - total_content_work_bytes
                        )
                        stream_budget = min(MAX_PDF_STREAM_BYTES, remaining_content_work_bytes // 2)
                        if stream_budget <= 0:
                            raise KnowledgeImportError("pdf_limit")
                        with apply_configuration(
                            maximum_declared_stream_length=stream_budget,
                            array_based_stream_maximum_output_length=stream_budget,
                            jbig2_maximum_output_length=stream_budget,
                            lzw_maximum_output_length=stream_budget,
                            run_length_maximum_output_length=stream_budget,
                            zlib_maximum_output_length=stream_budget,
                            zlib_maximum_recovery_input_length=min(
                                MAX_PDF_RECOVERY_BYTES, stream_budget
                            ),
                            image_maximum_buffer_size=stream_budget,
                        ):
                            decoded = stream_reference.get_object().get_data()
                        decoded_page_bytes += len(decoded)
                        if decoded_page_bytes > remaining_content_work_bytes // 2:
                            raise KnowledgeImportError("pdf_limit")
                    # The page-content work budget includes the bounded preflight
                    # decode and extraction's later parse. Other PDF resources
                    # are bounded by the isolated worker's memory and time limits.
                    total_content_work_bytes += decoded_page_bytes * 2
                remaining_content_work_bytes = MAX_PDF_CONTENT_WORK_BYTES - total_content_work_bytes
                if remaining_content_work_bytes <= 0:
                    raise KnowledgeImportError("pdf_limit")
                page_stream_limit = min(MAX_PDF_STREAM_BYTES, remaining_content_work_bytes)

                def count_text(text: Any, *_: Any) -> None:
                    nonlocal total_text_chars
                    total_text_chars += len(text)
                    if total_text_chars > MAX_RAG_CHARS:
                        raise KnowledgeImportError("content_too_large")

                forms_on_page = _form_xobjects(page)

                def count_form_invocations(
                    operator: Any,
                    operands: Any,
                    *_: Any,
                    form_names: set[str] = forms_on_page,
                ) -> None:
                    nonlocal total_form_invocations, total_content_work_bytes
                    if operator == b"Do" and operands and str(operands[0]) in form_names:
                        total_form_invocations += 1
                        total_content_work_bytes += MAX_PDF_STREAM_BYTES
                        if (
                            total_form_invocations > MAX_PDF_TOTAL_FORM_INVOCATIONS
                            or total_content_work_bytes > MAX_PDF_CONTENT_WORK_BYTES
                        ):
                            raise KnowledgeImportError("pdf_limit")

                try:
                    with apply_configuration(
                        maximum_declared_stream_length=page_stream_limit,
                        array_based_stream_maximum_output_length=remaining_content_work_bytes,
                        jbig2_maximum_output_length=page_stream_limit,
                        lzw_maximum_output_length=page_stream_limit,
                        run_length_maximum_output_length=page_stream_limit,
                        zlib_maximum_output_length=page_stream_limit,
                        zlib_maximum_recovery_input_length=min(
                            MAX_PDF_RECOVERY_BYTES, page_stream_limit
                        ),
                        image_maximum_buffer_size=page_stream_limit,
                        xform_maximum_invocations_per_extraction=min(
                            MAX_PDF_FORM_INVOCATIONS_PER_PAGE,
                            MAX_PDF_TOTAL_FORM_INVOCATIONS - total_form_invocations,
                            remaining_content_work_bytes // MAX_PDF_STREAM_BYTES,
                        ),
                    ):
                        page_text = (
                            page.extract_text(
                                visitor_text=count_text,
                                visitor_operand_before=count_form_invocations,
                            )
                            or ""
                        ).strip()
                except LimitReachedError as exc:
                    raise KnowledgeImportError("pdf_limit") from exc
                if page_text:
                    has_text = True
                    body = page_text
                else:
                    body = "> No selectable text was found on this page; OCR was not run."
                page_markdown = f"## Page {page_number}\n\n{body}"
                pages.append(page_markdown)
                markdown_chars += len(page_markdown) + 2
                if markdown_chars > MAX_RAG_CHARS:
                    raise KnowledgeImportError("content_too_large")
            if not has_text:
                raise KnowledgeImportError("pdf_no_text")
    except KnowledgeImportError:
        raise
    except LimitReachedError as exc:
        raise KnowledgeImportError("pdf_limit") from exc
    except MemoryError as exc:
        raise KnowledgeImportError("processing_failed") from exc
    except Exception as exc:
        raise KnowledgeImportError("invalid_pdf") from exc
    return "\n\n".join(pages) + "\n"


def _validate_docx_package(data: bytes) -> None:
    if not zipfile.is_zipfile(BytesIO(data)):
        raise KnowledgeImportError("invalid_docx")
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_PARTS:
                raise KnowledgeImportError("docx_limit")
            names: set[str] = set()
            total_bytes = 0
            for info in infos:
                if info.filename in names or info.flag_bits & 0x1:
                    raise KnowledgeImportError("invalid_docx")
                if info.file_size > MAX_DOCX_PART_BYTES:
                    raise KnowledgeImportError("docx_limit")
                names.add(info.filename)
                total_bytes += info.file_size
                if total_bytes > MAX_DOCX_TOTAL_BYTES:
                    raise KnowledgeImportError("docx_limit")
            if "word/document.xml" not in names:
                raise KnowledgeImportError("invalid_docx")
    except KnowledgeImportError:
        raise
    except MemoryError as exc:
        raise KnowledgeImportError("processing_failed") from exc
    except Exception as exc:
        raise KnowledgeImportError("invalid_docx") from exc


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>").strip()


def _table_to_markdown(table: Table) -> str:
    rows = [[_escape_table_cell(cell.text) for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    output = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    output.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(output)


def _paragraph_to_markdown(paragraph: Paragraph) -> str:
    text = paragraph.text.replace("\r", "\n").strip()
    if not text:
        return ""
    style_name = paragraph.style.name if paragraph.style is not None else ""
    heading = re.fullmatch(r"Heading\s+([1-6])", style_name, re.IGNORECASE)
    if style_name.casefold() == "title":
        return f"# {text}"
    if heading:
        return f"{'#' * int(heading.group(1))} {text}"
    if style_name.casefold().startswith("list bullet"):
        return f"- {text}"
    if style_name.casefold().startswith("list number"):
        return f"1. {text}"
    return text


def _docx_to_markdown(data: bytes) -> str:
    _validate_docx_package(data)
    try:
        document = load_docx(BytesIO(data))
        blocks = [
            _paragraph_to_markdown(block)
            if isinstance(block, Paragraph)
            else _table_to_markdown(block)
            for block in document.iter_inner_content()
        ]
        markdown = "\n\n".join(block for block in blocks if block).strip()
        if document.inline_shapes:
            marker = "> Embedded images were not converted; their text may be missing."
            markdown = f"{markdown}\n\n{marker}" if markdown else marker
        if not markdown:
            raise KnowledgeImportError("docx_no_text")
        if len(markdown) > MAX_RAG_CHARS:
            raise KnowledgeImportError("content_too_large")
    except KnowledgeImportError:
        raise
    except MemoryError as exc:
        raise KnowledgeImportError("processing_failed") from exc
    except Exception as exc:
        raise KnowledgeImportError("invalid_docx") from exc
    return markdown + "\n"


def convert_knowledge_upload(filename: str, data: bytes) -> tuple[str, bytes]:
    """Return a Markdown filename and bytes; source PDFs/DOCX never leave Maya."""

    _validate_filename(filename)
    if not data or len(data) > MAX_UPLOAD_FILE_BYTES:
        raise KnowledgeImportError("upload_size")
    extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if extension == "md":
        return filename, data
    if extension == "pdf":
        markdown = _convert_pdf_isolated(data).decode("utf-8")
    elif extension == "docx":
        _validate_docx_package(data)
        markdown = _convert_docx_isolated(data).decode("utf-8")
    else:
        raise KnowledgeImportError("unsupported_format")
    if len(markdown) > MAX_RAG_CHARS:
        raise KnowledgeImportError("content_too_large")
    return _converted_filename(filename), markdown.encode("utf-8")
