"""Pytest entry point for the formal TikTok content acceptance script."""

from acceptance import main


def test_formal_tiktok_packet_acceptance() -> None:
    assert main() == 0
