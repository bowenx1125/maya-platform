import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ErrorNotice } from "../components/ui";
import { PlatformApiError } from "../lib/api";

describe("error notices", () => {
  afterEach(() => {
    cleanup();
    document.querySelector(".notice-tray")?.remove();
  });

  it("names the missing record instead of a generic request failure", () => {
    render(
      <ErrorNotice
        inline
        notFound="agentNotFound"
        onRetry={() => undefined}
        error={
          new PlatformApiError(404, "not_found", {
            code: "not_found",
            message: "not_found",
          })
        }
      />,
    );
    const alert = screen.getByRole("alert");
    // Asking again for a deleted record cannot succeed.
    expect(within(alert).queryByRole("button", { name: "Retry" })).toBeNull();
    expect(alert.textContent).toContain(
      "This Agent was deleted or is no longer shared with you.",
    );
    expect(screen.queryByText("Request failed")).toBeNull();
    expect(screen.queryByText(/requested Maya resource/)).toBeNull();
  });

  it("keeps a server-named reason over the page's not-found text", () => {
    render(
      <ErrorNotice
        inline
        notFound="agentNotFound"
        error={
          new PlatformApiError(404, "agent_deleted", {
            code: "agent_deleted",
            message: "agent_deleted",
          })
        }
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "The publisher deleted this Agent.",
    );
  });

  it("floats outside the page top and closes with its X", () => {
    const { container } = render(
      <main>
        <h1>Page</h1>
        <ErrorNotice error={new TypeError("Failed to fetch")} />
      </main>,
    );
    const tray = document.querySelector(".notice-tray");
    expect(tray).not.toBeNull();
    expect(container.querySelector(".notice")).toBeNull();
    const alert = within(tray as HTMLElement).getByRole("alert");
    expect(alert.textContent).toContain(
      "Maya could not be reached. Check your connection and try again.",
    );
    fireEvent.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
