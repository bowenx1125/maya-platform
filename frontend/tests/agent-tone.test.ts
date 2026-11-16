import { describe, expect, it } from "vitest";

import { cardFromAgentMd, extractTone } from "../lib/agent-tone";

describe("extractTone", () => {
  it("reads a Tone bullet from AGENT.md", () => {
    const md =
      "# Ada\n\n## Speaking style\n\n- Tone: Firm and measured\n- Pattern: Short\n";
    expect(extractTone(md)).toBe("Firm and measured");
  });

  it("falls back when AGENT.md has no Tone", () => {
    expect(extractTone("# No tone\n", "  calm default  ")).toBe("calm default");
    expect(extractTone(null, null)).toBeNull();
  });

  it("builds a Check-card shaped object from AGENT.md", () => {
    const card = cardFromAgentMd(
      "# Ada\n\n## Identity\n\nA nurse.\n\n## Initial position\n\nPhones away.\n\n## Speaking style\n\nWarm.\n\n- Tone: Soft alto\n",
    );
    expect(card.identity).toBe("Ada");
    expect(card.position).toBe("Phones away.");
    expect(card.voice_style).toBe("Soft alto");
    expect(card.dropped).toEqual([]);
  });
});
