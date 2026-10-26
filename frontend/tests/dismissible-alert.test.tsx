import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { DismissibleAlert } from "../components/dismissible-alert";

describe("dismissible alerts", () => {
  afterEach(() => cleanup());

  it("closes with a compact × button and keeps its role", () => {
    render(
      <DismissibleAlert className="form-error">
        Generation did not complete: acceptance unknown.
      </DismissibleAlert>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.tagName).toBe("P");
    expect(alert.className).toContain("form-error");
    const close = screen.getByRole("button", { name: "Dismiss" });
    expect(close.className.split(" ")).toContain("alert-dismiss");
    expect(close.getAttribute("type")).toBe("button");
    expect(close.querySelector("svg")).toBeTruthy();
    expect(close.textContent).toBe("");
    fireEvent.click(close);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders a warning as a status line in the requested element", () => {
    render(
      <DismissibleAlert as="span" role="status" id="hint">
        Audio was not retained.
      </DismissibleAlert>,
    );
    const status = screen.getByRole("status");
    expect(status.tagName).toBe("SPAN");
    expect(status.id).toBe("hint");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows again when a new error arrives after an earlier one was closed", () => {
    function Harness() {
      const [error, setError] = useState<Error>(() => new Error("first"));
      return (
        <>
          <button type="button" onClick={() => setError(new Error("first"))}>
            fail again
          </button>
          <DismissibleAlert resetKey={error}>{error.message}</DismissibleAlert>
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    // Same wording, but a new failure: it must not stay swallowed.
    fireEvent.click(screen.getByRole("button", { name: "fail again" }));
    expect(screen.getByRole("alert").textContent).toBe("first");
  });

  it("shows again when its plain-text message changes", () => {
    const { rerender } = render(
      <DismissibleAlert>Old failure</DismissibleAlert>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<DismissibleAlert>Old failure</DismissibleAlert>);
    expect(screen.queryByRole("alert")).toBeNull();
    rerender(<DismissibleAlert>New failure</DismissibleAlert>);
    expect(screen.getByRole("alert").textContent).toBe("New failure");
  });

  it("shows again when the same mistake is repeated after it was closed", () => {
    // #141: forms clear and set the same text in one handler; React batches
    // both, so only a per-attempt reset key can bring the line back.
    function Harness() {
      const [error, setError] = useState<string | null>(null);
      const [attempt, setAttempt] = useState(0);
      return (
        <>
          <button
            type="button"
            onClick={() => {
              setAttempt((value) => value + 1);
              setError(null);
              setError("Select at least two Agents.");
            }}
          >
            done
          </button>
          {error ? (
            <DismissibleAlert resetKey={attempt}>{error}</DismissibleAlert>
          ) : null}
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "done" }));
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "done" }));
    expect(screen.getByRole("alert").textContent).toBe(
      "Select at least two Agents.",
    );
  });

  it("moves focus to the described field instead of the page body", () => {
    render(
      <form>
        <input aria-describedby="topic-error" aria-label="Topic" />
        <DismissibleAlert as="span" id="topic-error">
          Topic is required.
        </DismissibleAlert>
        <button type="submit">Done</button>
      </form>,
    );
    const close = screen.getByRole("button", { name: "Dismiss" });
    close.focus();
    fireEvent.click(close);
    expect(document.activeElement).toBe(screen.getByLabelText("Topic"));
  });

  it("falls back to the form's submit button", () => {
    render(
      <form>
        <DismissibleAlert>Enter your username.</DismissibleAlert>
        <button type="submit">Log in</button>
      </form>,
    );
    const close = screen.getByRole("button", { name: "Dismiss" });
    close.focus();
    fireEvent.click(close);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Log in" }),
    );
  });
});
