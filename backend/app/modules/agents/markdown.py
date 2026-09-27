"""Published Agent Markdown: authored text, not a second Persona schema."""

import hashlib

from pydantic import BaseModel, ConfigDict, Field


def markdown_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


class AgentMarkdown(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    markdown: str = Field(min_length=1)

    def as_payload(self) -> dict[str, object]:
        return {"name": self.name, "markdown": self.markdown}
