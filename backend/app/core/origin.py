"""Strict same-origin parsing and private Demo loopback compatibility."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.config import Settings

OriginTuple = tuple[str, str, int | None]


def origin_tuple(value: str | None) -> OriginTuple | None:
    """Parse an HTTP Origin without accepting URL components beyond origin."""

    if not value or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        # ``urlsplit`` drops empty ``?``/``#`` components and treats an
        # empty ``@`` userinfo as false-y; reject their raw delimiters too.
        if "?" in value or "#" in value or "@" in parsed.netloc:
            return None
        if parsed.port is None and parsed.netloc.endswith(":"):
            return None
        return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port
    except ValueError:
        return None


def _effective_port(origin: OriginTuple) -> int:
    scheme, _hostname, port = origin
    if port is not None:
        return port
    return 443 if scheme == "https" else 80


def _configured_origin(settings: Settings) -> OriginTuple | None:
    configured = getattr(settings, "gateway_origin", None) or settings.classroom_public_base_url
    if not isinstance(configured, str):
        return None
    return origin_tuple(configured.rstrip("/"))


def _demo_loopback_allowed(
    origin: OriginTuple,
    configured: OriginTuple,
    settings: Settings,
) -> bool:
    """Allow only HTTP loopback on the configured private Demo gateway port."""

    if not settings.demo_mode or settings.classroom_public_origin is None:
        return False
    if configured[0] != "http":
        return False
    if origin[0] != "http" or origin[1] not in {"localhost", "127.0.0.1"}:
        return False
    return _effective_port(origin) == _effective_port(configured)


def origin_allowed(
    value: str | None,
    settings: Settings,
    *,
    request_origin: str | None = None,
) -> bool:
    """Check a request/WS Origin against the configured private Demo policy.

    ``request_origin`` is the origin derived from the current HTTP request.
    It is used by CSRF checks to preserve ordinary same-origin requests.  The
    WebSocket route omits it when an explicit deployment origin exists so a
    crafted Host/Origin pair cannot become trusted through the socket URL.
    """

    origin = origin_tuple(value)
    if origin is None:
        return False
    configured = _configured_origin(settings)
    if configured is not None:
        return origin == configured or _demo_loopback_allowed(origin, configured, settings)
    # TestClient's default host is intentionally accepted only for test
    # processes when no deployment origin is configured. Production must have
    # an explicit classroom origin before a socket or mutation is trusted.
    return bool(
        settings.is_test and request_origin is not None and origin == origin_tuple(request_origin)
    )
