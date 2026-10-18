"""HTML reports a Team member saves for the Chat owner.

The model sends structured text through ``create_chat_html_report``; it never
writes HTML. The server stores that text with the Chat and its owner, renders
escaped HTML on download, and appends the real download link under the reply
(models invent paths). Only the Chat owner can download it, through the same
``owned_conversation`` check as every other Chat read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import Error, not_found
from app.modules.auth.dependencies import get_db, require_auth
from app.modules.auth.service import AuthContext
from app.modules.runtime_tools.registry import ToolCallIdentity, ToolSpec

from .models import ChatReport, Conversation

router = APIRouter(tags=["Chat"])

CHAT_REPORT_TOOL = "create_chat_html_report"
CHAT_REPORT_PATH_PREFIX = "/api/v1/conversations/"
_ENTRY_KINDS = frozenset({"team", "maya_team"})


class ReportEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(min_length=1, max_length=500)
    when: str | None = Field(default=None, max_length=40)
    speaker: str | None = Field(default=None, max_length=60)


class ReportMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    score: float | None = Field(default=None, ge=0, le=10)
    note: str | None = Field(default=None, max_length=500)


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=8000)
    evidence: list[ReportEvidence] = Field(default_factory=list, max_length=20)


class ChatReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=4000)
    metrics: list[ReportMetric] = Field(default_factory=list, max_length=12)
    sections: list[ReportSection] = Field(min_length=1, max_length=20)


def chat_report_download_path(conversation_id: str, report_id: str) -> str:
    return f"{CHAT_REPORT_PATH_PREFIX}{conversation_id}/reports/{report_id}"


def is_chat_report_path(path: str) -> bool:
    parts = path.removeprefix(CHAT_REPORT_PATH_PREFIX).split("/")
    if not path.startswith(CHAT_REPORT_PATH_PREFIX) or len(parts) != 3 or parts[1] != "reports":
        return False
    try:
        UUID(parts[0])
        UUID(parts[2])
    except ValueError:
        return False
    return True


def _authorize(db: Session, actor: AuthContext, row: Conversation, _payload: BaseModel) -> None:
    if (
        row.user_id != actor.user.id
        or row.withdrawn_at is not None
        or row.entry_kind not in _ENTRY_KINDS
    ):
        raise not_found()


def _create(
    db: Session,
    actor: AuthContext,
    row: Conversation,
    payload: BaseModel,
    event_id: str,
    _identity: ToolCallIdentity,
) -> dict[str, Any]:
    arguments = ChatReportArguments.model_validate(payload)
    report = db.scalar(select(ChatReport).where(ChatReport.client_event_id == event_id))
    if report is None:
        report = ChatReport(
            id=event_id,
            conversation_id=row.id,
            owner_user_id=actor.user.id,
            client_event_id=event_id,
            title=arguments.title,
            content_json=arguments.model_dump_json(),
            created_at=datetime.now(UTC),
        )
        db.add(report)
        db.flush()
    elif report.conversation_id != row.id or report.owner_user_id != actor.user.id:
        raise not_found()
    return {
        "report_id": report.id,
        "title": report.title,
        "download_path": chat_report_download_path(row.id, report.id),
    }


def chat_report_tools() -> dict[str, ToolSpec]:
    return {
        CHAT_REPORT_TOOL: ToolSpec(
            CHAT_REPORT_TOOL,
            "Public",
            "Save a downloadable HTML report for the user of this Team Chat. Call it only "
            "when the user asks you for a report, and only after you have the analysis: "
            "title, a short summary, optional 0-10 metrics with notes, and sections whose "
            "evidence quotes the chat or attachments word for word with their time. Write "
            "plain text, not HTML or Markdown. Only this Chat's owner can download it. "
            "Do not write a download link, path or token in your reply: the server adds "
            "the real download link under it.",
            ChatReportArguments,
            _authorize,
            _create,
            entry_kinds=_ENTRY_KINDS,
        )
    }


_STYLE = """
body{margin:0;background:#f6f4f1;color:#22201d;font:16px/1.65 -apple-system,
BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif}
main{max-width:820px;margin:0 auto;padding:40px 22px 64px}
h1{font-size:28px;line-height:1.3;margin:0 0 6px}
.meta{color:#77706a;font-size:13px;margin:0 0 28px}
.summary{background:#fff;border-radius:16px;padding:20px 22px;box-shadow:0 1px 3px #0001}
h2{font-size:20px;margin:36px 0 10px}
p{margin:0 0 12px;white-space:pre-wrap}
.metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;
margin-top:20px}
.metric{background:#fff;border-radius:14px;padding:14px 16px;box-shadow:0 1px 3px #0001}
.metric b{display:block;font-size:14px}.metric .score{font-size:24px;font-weight:700}
.bar{height:6px;border-radius:3px;background:#ebe6e0;margin:6px 0}
.bar i{display:block;height:6px;border-radius:3px;background:#c4654f}
.metric small{color:#77706a}
blockquote{margin:8px 0;padding:8px 14px;border-left:3px solid #c4654f;background:#fff;
border-radius:0 10px 10px 0;white-space:pre-wrap}
blockquote cite{display:block;color:#77706a;font-size:12px;font-style:normal}
footer{margin-top:48px;color:#77706a;font-size:12px}
"""


def render_chat_report_html(report: ChatReport) -> str:
    content = ChatReportArguments.model_validate_json(report.content_json)
    created = report.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    parts = [
        "<!doctype html>",
        '<html lang="zh"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(content.title)}</title><style>{_STYLE}</style></head><body><main>",
        f"<h1>{escape(content.title)}</h1>",
        f'<p class="meta">Maya · {escape(created.strftime("%Y-%m-%d %H:%M UTC"))}</p>',
        f'<section class="summary"><p>{escape(content.summary)}</p></section>',
    ]
    if content.metrics:
        parts.append('<section class="metrics">')
        for metric in content.metrics:
            score = ""
            if metric.score is not None:
                width = round(metric.score * 10)
                score = (
                    f'<span class="score">{metric.score:g}/10</span>'
                    f'<div class="bar"><i style="width:{width}%"></i></div>'
                )
            note = f"<small>{escape(metric.note)}</small>" if metric.note else ""
            parts.append(f'<div class="metric"><b>{escape(metric.label)}</b>{score}{note}</div>')
        parts.append("</section>")
    for section in content.sections:
        parts.append(f"<section><h2>{escape(section.heading)}</h2>")
        parts.extend(
            f"<p>{escape(paragraph.strip())}</p>"
            for paragraph in section.body.split("\n\n")
            if paragraph.strip()
        )
        for item in section.evidence:
            cite = " · ".join(escape(value) for value in (item.when, item.speaker) if value)
            cite_html = f"<cite>{cite}</cite>" if cite else ""
            parts.append(f"<blockquote>{cite_html}{escape(item.quote)}</blockquote>")
        parts.append("</section>")
    parts.append(
        "<footer>Generated in Maya from this Chat and its attachments. For reflection, "
        "not a diagnosis. 仅供参考，不构成诊断。</footer></main></body></html>"
    )
    return "\n".join(parts)


@router.get(
    "/conversations/{conversation_id}/reports/{report_id}",
    operation_id="downloadConversationReport",
    response_class=Response,
    responses={
        200: {"content": {"text/html": {"schema": {"type": "string"}}}},
        404: {"model": Error},
    },
)
def download_conversation_report(
    conversation_id: UUID,
    report_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    from .chat import owned_conversation

    row = owned_conversation(db, context, str(conversation_id))
    report = db.get(ChatReport, str(report_id))
    if (
        report is None
        or report.conversation_id != row.id
        or report.owner_user_id != context.user.id
    ):
        raise not_found()
    body = render_chat_report_html(report)
    filename = f"{report.title[:80]}.html"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"report.html\"; filename*=UTF-8''{quote(filename)}"
            ),
            # Escaped already; the sandbox keeps a saved copy inert as well.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


def purge_conversation_reports(db: Session, conversation_id: str) -> None:
    """Remove a deleted Chat's reports. The caller commits before this runs."""

    db.execute(delete(ChatReport).where(ChatReport.conversation_id == conversation_id))
    db.commit()
