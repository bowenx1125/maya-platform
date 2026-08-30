# ADR-002: Immutable KnowledgeSnapshot

Status: `ACCEPTED`

Publishing freezes enabled Markdown bytes, source lineage, chunks, vectors and
processing metadata into a KnowledgeSnapshot owned by one AgentVersion. Later document
or Embedding changes create a new version/snapshot and never rewrite history.
