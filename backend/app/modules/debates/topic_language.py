"""Accept authored topics independently of the requested speech language."""

from __future__ import annotations

import unicodedata

TOPIC_LANGUAGE_ERROR_CODE = "topic_language_invalid"
TOPIC_LANGUAGE_ERROR_MESSAGE = "The debate topic must not be blank."
TOPIC_LANGUAGE_ERROR_DETAILS = {"field": "topic"}


class TopicLanguageError(ValueError):
    code = TOPIC_LANGUAGE_ERROR_CODE
    message = TOPIC_LANGUAGE_ERROR_MESSAGE

    @property
    def details(self) -> dict[str, str]:
        return dict(TOPIC_LANGUAGE_ERROR_DETAILS)

    def __init__(self) -> None:
        super().__init__(self.message)


def normalize_model_text(value: str) -> str:
    """Keep meaningful punctuation/scripts while removing invisible controls."""
    cleaned = "".join(
        " " if char.isspace() else char
        for char in unicodedata.normalize("NFC", value)
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    return " ".join(cleaned.split())


def model_topic(topic: str, background: str = "") -> str:
    title = normalize_model_text(topic)
    context = normalize_model_text(background)
    return f"Topic: {title}\nBackground (teacher-provided context): {context}" if context else title


def validate_topic(value: str, output_language: str = "en") -> str:
    if not isinstance(value, str) or not normalize_model_text(value):
        raise TopicLanguageError()
    return value.strip()


def validate_english_topic(value: str) -> str:
    return validate_topic(value)
