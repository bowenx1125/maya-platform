import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentCard } from "../components/ui/agent-card";

afterEach(cleanup);

describe("U3 card rename sticker", () => {
  it("shows the server '!' sticker outside the clipping frame", () => {
    const { container } = render(
      <ul>
        <AgentCard
          id="c"
          name="Rename me"
          href="#"
          label="V2.1"
          pending={false}
          visibility="private"
          visibilityLabel="Private"
          mascot="scroll"
          deleteLabel="Delete"
          rename={{
            fieldLabel: "Name",
            onRename: async () => false,
            errorId: "e",
            invalid: true,
          }}
        />
      </ul>,
    );
    const sticker = container.querySelector('[data-sticker="server"]');
    expect(sticker).not.toBeNull();
    expect(sticker?.parentElement?.tagName).toBe("LI");
    expect(container.querySelector("[data-checklist-badge]")).toBeNull();
  });
});
