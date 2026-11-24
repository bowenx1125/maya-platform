"""Optional learning-data research consent recorded at password login."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.modules.auth.models import UserLearningResearchConsent

CONSENT_COPY_VERSION = "learning-data-consent-v1"


def apply_login_research_consent(
    db: Session,
    *,
    user_id: str,
    consented: bool,
    now: datetime | None = None,
) -> None:
    """Upsert or revoke research consent after a successful password verify.

    A missing row means not consented. Unticking on a later login revokes an
    existing true row. Leaving the box unchecked when no row exists writes
    nothing, so existing accounts stay default-false without mass inserts.
    """

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)

    row = db.get(UserLearningResearchConsent, user_id)
    if consented:
        if row is None:
            db.add(
                UserLearningResearchConsent(
                    user_id=user_id,
                    consented=True,
                    consent_copy_version=CONSENT_COPY_VERSION,
                    updated_at=timestamp,
                )
            )
            return
        row.consented = True
        row.consent_copy_version = CONSENT_COPY_VERSION
        row.updated_at = timestamp
        return

    if row is None or not row.consented:
        return
    row.consented = False
    row.consent_copy_version = CONSENT_COPY_VERSION
    row.updated_at = timestamp


__all__ = ["CONSENT_COPY_VERSION", "apply_login_research_consent"]
