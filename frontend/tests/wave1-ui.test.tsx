import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlatformApiError } from "../lib/api";
import { ErrorNotice, StatusBadge } from "../components/ui";

describe("Wave 1A state and permission feedback", () => {
  it("keeps a revision conflict distinct from a generic request error", () => {
    render(
      <ErrorNotice
        error={
          new PlatformApiError(409, "Draft changed", { code: "stale_revision" })
        }
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "Revision conflict",
    );
    expect(screen.getByRole("alert").textContent).toContain("Please refresh");
  });

  it("shows indexing failure as a visible, non-success state", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("failed")).toBeTruthy();
    expect(screen.getByText("failed").className).toContain("status-bad");
  });

  it("preserves the teacher/student boundary in the platform error shape", () => {
    const error = new PlatformApiError(404, "Not found", { code: "not_found" });
    expect(error.status).toBe(404);
    expect(error.code).toBe("not_found");
    expect(error.message).toBe("Not found");
  });
});
