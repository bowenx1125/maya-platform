from app.modules.agents.tone import extract_card_tone, extract_tone


def test_extract_tone_from_agent_md_bullet() -> None:
    md = (
        "# Ada\n\n## Speaking style\n\n"
        "- Tone: Firm and measured\n"
        "- Argument pattern: Short claims\n"
    )
    assert extract_tone(md) == "Firm and measured"
    assert extract_card_tone(md) == "Firm and measured"


def test_extract_tone_falls_back() -> None:
    assert extract_tone("", fallback="  calm default  ") == "calm default"
    assert extract_tone(None, fallback=None) is None
    assert extract_tone("# No tone here\n", fallback="") is None


def test_extract_tone_truncates_card_line() -> None:
    long = "x" * 200
    md = f"- Tone: {long}\n"
    assert extract_card_tone(md) == "x" * 120
