"""An allowed UUID is not a phone number; identity and prose gates remain strict."""

import pytest
from app.providers.llm_privacy import LLMOutboundPrivacyError, _scan_value

PUBLIC_ID = "00000000-0000-4000-8000-a13800138000"


def test_public_identifier_with_phone_shaped_suffix_is_allowed():
    _scan_value(PUBLIC_ID, path=("evidence_id",), identity_tokens=(), workspace_id=None)


@pytest.mark.parametrize(
    ("value", "path", "tokens"),
    [
        (PUBLIC_ID, ("speech",), ()),
        (PUBLIC_ID, ("evidence_id",), (PUBLIC_ID,)),
        ("13800138000", ("evidence_id",), ()),
        ("Call 13800138000", ("speech",), ()),
        (PUBLIC_ID + " 13800138000", ("evidence_id",), ()),
    ],
)
def test_uuid_exception_does_not_admit_identity_or_phone_text(value, path, tokens):
    with pytest.raises(LLMOutboundPrivacyError):
        _scan_value(value, path=path, identity_tokens=tokens, workspace_id=None)
