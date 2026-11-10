from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import AgentEditAudit, Group, User
from app.seed import COURSE_ID
from fastapi.testclient import TestClient
from sqlalchemy import event

from tests.conftest import login
from tests.test_mayaform_team_conversations import _make_agent_version
from tests.test_mayaform_teams import BOWEN_ID, GROUP_ID, MAYA_ID

URL = f"/api/v1/courses/{COURSE_ID}/chat-agents"
EDITED_AT = datetime(2026, 11, 1, 12, 30, tzinfo=UTC)


def _agent(database: Any, *, group: bool, audit: bool) -> str:
    agent_id, _ = _make_agent_version(
        database,
        owner_id=BOWEN_ID if group else MAYA_ID,
        visibility="public" if group else "private",
        name=f"Card {uuid4()}",
        group_id=GROUP_ID if group else None,
    )
    if audit:
        with database.session() as db:
            db.add(
                AgentEditAudit(
                    agent_id=agent_id, last_edited_by_user_id=MAYA_ID, last_edited_at=EDITED_AT
                )
            )
            db.commit()
    return agent_id


def test_group_and_personal_cards_with_and_without_audit(client: TestClient, database: Any) -> None:
    login(client, "maya")
    group_id = _agent(database, group=True, audit=True)
    personal_id = _agent(database, group=False, audit=False)
    with database.session() as db:
        group_name = db.get(Group, GROUP_ID).name
        editor_name = db.get(User, MAYA_ID).display_name
    response = client.get(URL)
    assert response.status_code == 200
    cards = {card["agent_id"]: card for card in response.json()}
    assert cards[group_id]["group_name"] == group_name
    assert cards[group_id]["last_edited_by_name"] == editor_name
    assert datetime.fromisoformat(cards[group_id]["last_edited_at"]) == EDITED_AT
    assert cards[personal_id]["group_name"] is None
    assert cards[personal_id]["last_edited_by_name"] is None
    assert cards[personal_id]["last_edited_at"] is None


def test_missing_audit_user_is_null(client: TestClient, database: Any) -> None:
    login(client, "maya")
    agent_id = _agent(database, group=False, audit=True)
    with database.session() as db:
        db.get(AgentEditAudit, agent_id).last_edited_by_user_id = str(uuid4())
        db.commit()
    response = client.get(URL)
    assert response.status_code == 200
    card = next(card for card in response.json() if card["agent_id"] == agent_id)
    assert card["last_edited_by_name"] is None
    assert datetime.fromisoformat(card["last_edited_at"]) == EDITED_AT


def test_query_count_does_not_grow_with_agents(client: TestClient, database: Any) -> None:
    login(client, "maya")
    _agent(database, group=True, audit=True)

    def count_queries() -> tuple[int, int]:
        statements: list[str] = []

        def tick(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            statements.append(statement)

        event.listen(database.engine, "before_cursor_execute", tick)
        try:
            response = client.get(URL)
        finally:
            event.remove(database.engine, "before_cursor_execute", tick)
        assert response.status_code == 200
        return len(statements), len(response.json())

    one_count, one_size = count_queries()
    for index in range(6):
        _agent(database, group=index % 2 == 0, audit=index % 2 == 0)
    many_count, many_size = count_queries()
    assert many_size == one_size + 6
    assert many_count == one_count
