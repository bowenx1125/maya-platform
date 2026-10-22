"""Check text shared by the models and migration 0078.

A deleted Agent, Team, or chat leaves history readable. The live shape of each
check is unchanged; a detached branch allows the foreign keys to be cleared
once a name snapshot is stored.
"""

CONVERSATION_ENTRY_CHECK = (
    "(entry_kind = 'agent' AND origin = 'single_agent' AND team_id IS NULL "
    "AND team_version_id IS NULL AND team_owner_user_id IS NULL "
    "AND team_name_snapshot IS NULL AND team_authorization_epoch IS NULL "
    "AND publication_id IS NULL AND publication_epoch IS NULL AND ("
    "(source_removed_at IS NULL AND agent_version_id IS NOT NULL) OR "
    "(source_removed_at IS NOT NULL AND agent_version_id IS NULL AND snapshot_id IS NULL "
    "AND history_agent_id IS NOT NULL AND history_agent_version_id IS NOT NULL)"
    ")) OR ("
    "entry_kind IN ('team', 'maya_team') AND agent_version_id IS NULL AND snapshot_id IS NULL "
    "AND team_name_snapshot IS NOT NULL AND team_authorization_epoch IS NOT NULL "
    "AND team_authorization_epoch >= 0 AND ("
    "(source_removed_at IS NULL AND team_id IS NOT NULL AND team_version_id IS NOT NULL "
    "AND team_owner_user_id IS NOT NULL AND ("
    "(entry_kind = 'team' AND origin = 'custom_team' AND publication_id IS NULL "
    "AND publication_epoch IS NULL) OR "
    "(entry_kind = 'maya_team' AND origin = 'published_course_team' "
    "AND publication_id IS NOT NULL AND publication_epoch IS NOT NULL "
    "AND publication_epoch >= 0))) OR ("
    "source_removed_at IS NOT NULL AND team_id IS NULL AND team_version_id IS NULL "
    "AND publication_id IS NULL AND history_team_id IS NOT NULL "
    "AND history_team_version_id IS NOT NULL)))"
)

LEARNING_TEAM_ORIGIN_CHECK = (
    "((origin = 'single_agent' AND team_id IS NULL AND team_version_id IS NULL) OR "
    "(origin IN ('custom_team', 'published_course_team') AND team_id IS NOT NULL "
    "AND team_version_id IS NOT NULL) OR "
    "(origin IN ('custom_team', 'published_course_team') AND team_id IS NULL "
    "AND team_version_id IS NULL AND team_name_snapshot IS NOT NULL "
    "AND length(trim(team_name_snapshot)) > 0))"
)

LEARNING_REVISION_EXECUTOR_CHECK = (
    "(revision_source='user_authored' AND attempt_id IS NULL "
    "AND evaluator_team_member_id IS NULL AND evaluator_agent_version_id IS NULL "
    "AND editor_team_member_id IS NULL AND editor_agent_version_id IS NULL "
    "AND source_model_call_id IS NULL AND source_tool_call_id IS NULL) OR "
    "(revision_source='model_evaluation' AND attempt_id IS NOT NULL "
    "AND evaluator_team_member_id IS NOT NULL AND evaluator_agent_version_id IS NOT NULL "
    "AND editor_team_member_id IS NULL AND editor_agent_version_id IS NULL "
    "AND source_model_call_id IS NOT NULL AND source_tool_call_id IS NOT NULL) OR "
    "(revision_source='practice_agent_edit' AND attempt_id IS NULL "
    "AND evaluator_team_member_id IS NULL AND evaluator_agent_version_id IS NULL "
    "AND editor_agent_version_id IS NOT NULL "
    "AND ((origin='single_agent' AND team_id IS NULL AND team_version_id IS NULL "
    "AND editor_team_member_id IS NULL) OR "
    "(origin IN ('custom_team', 'published_course_team') "
    "AND team_id IS NOT NULL AND team_version_id IS NOT NULL "
    "AND editor_team_member_id IS NOT NULL) OR "
    "(origin IN ('custom_team', 'published_course_team') "
    "AND team_id IS NULL AND team_version_id IS NULL "
    "AND team_name_snapshot IS NOT NULL AND length(trim(team_name_snapshot)) > 0)) "
    "AND source_model_call_id IS NOT NULL AND source_tool_call_id IS NOT NULL)"
)

ATTEMPT_ABANDON_REASON_CHECK = (
    "abandonment_reason IS NULL OR abandonment_reason IN "
    "('user_redo', 'user_abandoned', 'chat_withdrawn', 'source_deleted')"
)

ATTEMPT_QUESTION_SNAPSHOT_CHECK = (
    "(status='not_presented' AND presented_at IS NULL AND question_version_id IS NULL "
    "AND content_json IS NULL AND content_hash IS NULL) OR "
    "(status IN ('presented', 'resolved') AND presented_at IS NOT NULL "
    "AND content_json IS NOT NULL AND length(content_hash)=64)"
)
