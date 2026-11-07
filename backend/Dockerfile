FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# FFmpeg is required by the voice-enrollment boundary even when the host has it installed.
# deb.debian.org is listed over HTTP. A build host whose HTTP path returns 500
# (198.18.0.1:80) can still use the same official mirrors over HTTPS. Only the
# scheme changes; Signed-By stays the Debian archive keyring.
ARG FFMPEG_VERSION=7:5.1.9-0+deb12u1
RUN sed -i 's|^URIs: http://deb.debian.org|URIs: https://deb.debian.org|' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends --yes "ffmpeg=${FFMPEG_VERSION}" \
    && ffmpeg -version | grep -F "ffmpeg version 5.1.9" \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

# Install the exact uv tool and resolve every runtime package from the checked-in lock.
# No scaffold fallback is allowed once the Wave 0 backend exists.
RUN python -m pip install --no-cache-dir --upgrade pip==25.2 uv==0.12.0 \
    && uv sync --frozen --no-dev --no-editable

EXPOSE 8000

# Readiness is an actual backend application contract. A missing/unready app stays unhealthy.
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s --retries=6 \
    CMD python -c "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2); raise SystemExit(0 if response.status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
