"""Debate domain modules.

Wave 2 keeps generation and playback concerns in separate subpackages.  The
M11 generation package is deliberately provider-neutral so the setup and
playback workers can depend on stable contracts without importing an ORM or a
supplier SDK.
"""
