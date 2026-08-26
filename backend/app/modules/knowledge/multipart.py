"""Small dependency-free multipart/form-data parser for Markdown uploads."""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from fastapi import Request


async def parse_upload(request: Request) -> tuple[dict[str, str], str, bytes]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart/form-data is required")
    raw = await request.body()
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode() + b"\r\n\r\n" + raw
    )
    fields: dict[str, str] = {}
    filename = ""
    payload = b""
    for part in message.iter_parts():
        name_value = part.get_param("name", header="content-disposition")
        if not isinstance(name_value, str) or not name_value:
            continue
        if name_value == "file":
            filename = part.get_filename() or ""
            decoded = part.get_payload(decode=True)
            payload = decoded if isinstance(decoded, bytes) else b""
        else:
            decoded = part.get_payload(decode=True)
            value = decoded if isinstance(decoded, bytes) else str(decoded or "").encode("utf-8")
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
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed
