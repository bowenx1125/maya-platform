"""Before a formal test starts, the Guide answers in prose and invites 正式测评.

Prod (2026-10-19, Team 起点问卷): the student wrote "你好介绍你们团队" before
any test. The Guide put its whole introduction into assessment_action's
guidance; the Tool returned assessment_attempt_not_active and ended the turn,
so the Guide showed nothing. The owner chose a prompt fix: with no attempt,
the Guide does not call assessment_action except for an explicit start, and
leads the student to the formal test. A live attempt is unchanged.
"""

from __future__ import annotations

from app.modules.workspace import team_runtime as runtime

_MD = "# Guide\n\nLead the room."


def _system(**kwargs: object) -> str:
    return runtime._member_system(_MD, "{}", speaker_name="Guider", **kwargs)  # type: ignore[arg-type]


def test_guide_without_attempt_replies_in_prose_and_invites_the_test() -> None:
    leader = _system(is_leader=True)
    assert "No formal assessment has started in this chat." in leader
    assert "Do not call assessment_action for this message unless the student" in leader
    assert "only then call it with start_request" in leader
    assert "never put that reply into a Tool argument" in leader
    assert "introduce the Team and its members when asked" in leader
    assert "start the formal test by saying 正式测评" in leader
    assert "not on every reply" not in leader


def test_other_members_without_attempt_do_not_call_the_action() -> None:
    member = _system(is_leader=False)
    assert "do not call assessment_action" in member
    assert "saying 正式测评" not in member
    assert "start the formal test" not in member


def test_live_attempt_keeps_the_action_protocol() -> None:
    for is_leader in (True, False):
        active = _system(is_leader=is_leader, assessment_active=True)
        assert "<active_assessment_action_protocol>" in active
        assert "Call assessment_action to classify" in active
        assert "No formal assessment has started" not in active
        assert "Do not call assessment_action for this message" not in active


def test_closed_attempt_keeps_the_earlier_guide_rule() -> None:
    leader = _system(is_leader=True, attempt_closed=True)
    assert "not on every reply" in leader
    assert "No formal assessment has started" not in leader
    member = _system(is_leader=False, attempt_closed=True)
    assert "No formal assessment has started" not in member


def test_teacher_viewer_is_not_invited() -> None:
    teacher = _system(is_leader=True, viewer_is_teacher=True)
    assert "start the formal test by saying 正式测评" not in teacher


def test_team_without_assessment_has_no_action_wording() -> None:
    ordinary = _system(is_leader=True, assessment_capable=False)
    assert "assessment_action" not in ordinary
    assert "正式测评" not in ordinary
