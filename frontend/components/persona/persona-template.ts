/**
 * Shared authoring helpers for the current five-section Persona template.
 *
 * The Agent display name is the only name input.  The Markdown H1 is derived
 * from it here so a newly created draft cannot start with a second, stale
 * name field.  Historical seven-section Markdown remains readable through
 * the versioned backend compiler and is intentionally not rewritten here.
 */

export const PERSONA_V2_SECTION_NAMES = [
  "Identity",
  "Cultural lens",
  "Core values",
  "Initial position",
  "Speaking style",
] as const;

export const PERSONA_TEMPLATE_V2_PLACEHOLDER_NAME = "Agent name";

const PERSONA_V2_BODY = `
## Identity

- Role: Describe the cultural or social role this Agent represents.
- Historical or cultural context: Describe the context that should shape interpretation.

## Cultural lens

- Describe the lens this Agent uses to understand the topic.

## Core values

- Name one value that should guide this Agent's judgment.

## Initial position

Describe the Agent's starting position and the trade-offs it recognizes.

## Speaking style

- Tone: Describe the desired tone.
- Argument pattern: Describe how the Agent builds an argument.
- Concession style: Describe how the Agent acknowledges reasonable concerns.
- Question style: Describe how the Agent asks questions.
`;

/** The stable five-section outline used when a new draft has no name yet. */
export const PERSONA_OUTLINE_V2 = `# ${PERSONA_TEMPLATE_V2_PLACEHOLDER_NAME}${PERSONA_V2_BODY}`;

/** Backwards-readable alias for callers that name outlines as templates. */
export const PERSONA_TEMPLATE_V2 = PERSONA_OUTLINE_V2;
export const AGENT_OUTLINE_V2 = PERSONA_OUTLINE_V2;

/**
 * Build a valid current template from the one authoritative Agent name.
 * Whitespace around the display name is removed to match the compiler's
 * identity comparison; internal content is left untouched and unlocalized.
 */
export function buildPersonaTemplate(name: string): string {
  const displayName = name.trim() || PERSONA_TEMPLATE_V2_PLACEHOLDER_NAME;
  return `# ${displayName}${PERSONA_V2_BODY}`;
}

export const buildPersonaTemplateV2 = buildPersonaTemplate;

/**
 * Update only the H1 in an existing current template when the display name
 * changes.  A non-template or legacy document is returned unchanged so an
 * author never loses authored bytes through a convenience helper.
 */
export function syncPersonaTemplateName(source: string, name: string): string {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const displayName = name.trim();
  if (!displayName || !isCurrentPersonaTemplate(lines)) return source;
  lines[0] = `# ${displayName}`;
  return lines.join("\n");
}

function isCurrentPersonaTemplate(lines: readonly string[]): boolean {
  if (!lines[0]?.startsWith("# ")) return false;
  const headings = lines
    .filter((line) => line.startsWith("## "))
    .map((line) => line.slice(3));
  return (
    headings.length === PERSONA_V2_SECTION_NAMES.length &&
    headings.every(
      (heading, index) => heading === PERSONA_V2_SECTION_NAMES[index],
    )
  );
}
