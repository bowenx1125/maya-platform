import pytest
from app.core.version_label import agent_version_label, team_version_label, version_label


@pytest.mark.parametrize(
    ("ordinal", "label"),
    [
        (1, "V1.0"),
        (2, "V1.1"),
        (6, "V1.5"),
        (10, "V1.9"),
        (11, "V2.0"),
        (12, "V2.1"),
        (13, "V2.2"),
        (101, "V11.0"),
        (0, "V1.0"),
        (-2, "V1.0"),
    ],
)
def test_nth_version_reads_one_point_oh_plus_tenths(ordinal: int, label: str) -> None:
    assert version_label(ordinal) == label


def test_agents_count_from_seq_zero_and_teams_from_seq_one() -> None:
    assert agent_version_label(0) == "V1.0"
    assert agent_version_label(10) == "V2.0"
    assert agent_version_label(12) == "V2.2"
    assert team_version_label(1) == "V1.0"
    assert team_version_label(11) == "V2.0"
    assert team_version_label(12) == "V2.1"
