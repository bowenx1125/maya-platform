"""Small dependency-free multipart/form-data parser for Markdown uploads."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from fastapi import Request
from starlette.requests import ClientDisconnect

MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_FILE_BYTES + 64 * 1024
MAX_UPLOAD_FIELD_BYTES = 16 * 1024
MAX_UPLOAD_PARTS = 16


class UploadTooLargeError(ValueError):
    """The raw multipart request or uploaded file exceeds its byte limit."""


async def parse_upload(request: Request) -> tuple[dict[str, str], str, bytes]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart/form-data is required")
    raw_length = request.headers.get("content-length")
    if raw_length:
        try:
            declared_length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if declared_length < 0:
            raise ValueError("invalid content length")
        if declared_length > MAX_UPLOAD_REQUEST_BYTES:
            raise UploadTooLargeError("upload is too large")
    chunks = bytearray()
    total_seen = 0
    try:
        async for chunk in request.stream():
            if not isinstance(chunk, bytes):
                raise ValueError("invalid upload body")
            total_seen += len(chunk)
            if total_seen > MAX_UPLOAD_REQUEST_BYTES:
                raise UploadTooLargeError("upload is too large")
            chunks.extend(chunk)
    except ClientDisconnect as exc:
        raise ValueError("upload was interrupted") from exc
    raw = bytes(chunks)
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + raw
    )
    if not message.is_multipart():
        raise ValueError("multipart body is invalid")
    fields: dict[str, str] = {}
    filename = ""
    payload = b""
    file_seen = False
    part_count = 0
    for part in message.iter_parts():
        part_count += 1
        if part_count > MAX_UPLOAD_PARTS:
            raise ValueError("too many upload fields")
        name_value = part.get_param("name", header="content-disposition")
        if not isinstance(name_value, str) or not name_value:
            raise ValueError("upload field name is required")
        decoded = part.get_payload(decode=True)
        value = decoded if isinstance(decoded, bytes) else str(decoded or "").encode("utf-8")
        if name_value == "file":
            if file_seen or part.get_filename() is None:
                raise ValueError("exactly one file is required")
            file_seen = True
            if len(value) > MAX_UPLOAD_FILE_BYTES:
                raise UploadTooLargeError("upload is too large")
            filename = part.get_filename() or ""
            payload = value
        else:
            if part.get_filename() is not None or len(value) > MAX_UPLOAD_FIELD_BYTES:
                raise ValueError("invalid upload field")
            if name_value in fields:
                raise ValueError("duplicate upload field")
            fields[name_value] = value.decode("utf-8", errors="strict")
    if not filename:
        raise ValueError("file is required")
    return fields, filename, payload


def integer_field(fields: dict[str, str], name: str, *, required: bool = False) -> int | None:
    value = fields.get(name)
    if value is None or value == "":
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed
