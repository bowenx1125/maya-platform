"""Sampled browser timings, written to the log next to request_timing lines.

The browser reports how long a few key moments took (Next to first audio,
first page render, assessment submit). Nothing is stored: each metric becomes
one ``client_metric`` log line with the metric name, the duration, the page's
route template and the replica host. No user, session or record id is logged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import Error
from app.core.request_timing import HOST
from app.modules.auth.dependencies import require_authenticated_mutation
from app.modules.auth.service import AuthContext

logger = logging.getLogger("maya.client_metrics")
router = APIRouter(tags=["Telemetry"])

ClientMetricName = Literal["debate_next_to_play", "page_first_render", "assessment_submit"]
# A segment that looks like a record id is folded into "{id}" even if the
# browser forgot to, so a page path can never carry one into the log.
_ID_SEGMENT = re.compile(r"^(?:[0-9a-fA-F-]{8,}|[0-9]+)$")


class ClientMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ClientMetricName
    ms: float = Field(ge=0, le=600000)
    page: str | None = Field(default=None, max_length=120, pattern=r"^/[A-Za-z0-9/_{}\[\]-]*$")


class ClientMetricsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[ClientMetric] = Field(min_length=1, max_length=20)


def page_template(page: str | None) -> str | None:
    if page is None:
        return None
    return "/".join("{id}" if _ID_SEGMENT.match(part) else part for part in page.split("/"))


@router.post(
    "/client-metrics",
    status_code=204,
    operation_id="reportClientMetrics",
    responses={
        204: {"description": "Metrics accepted and logged; nothing is stored."},
        401: {"model": Error},
        403: {"model": Error},
    },
)
def report_client_metrics(
    payload: ClientMetricsReport,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    _context: AuthContext = Depends(require_authenticated_mutation),
) -> Response:
    for metric in payload.metrics:
        record = {
            "event": "client_metric",
            "name": metric.name,
            "ms": round(metric.ms, 1),
            "page": page_template(metric.page),
            "host": HOST,
        }
        logger.info(json.dumps(record, separators=(",", ":")))
    return Response(status_code=204)
