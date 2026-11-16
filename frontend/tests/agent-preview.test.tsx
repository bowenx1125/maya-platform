import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  PreviewController,
  type PreviewReply,
  type PreviewState,
} from "../components/agent-preview/preview-controller";
import { AgentPreview } from "../components/agent-preview/agent-preview";
import { PreviewControls } from "../components/agent-preview/preview-controls";
import { AvatarEditor } from "../components/avatar/avatar-editor";
import { AVATAR_TEMPLATE_DEFAULT_CONFIGS as defaults } from "../components/avatar/types";
vi.mock("../components/avatar/egg-canvas", () => ({
  EggCanvas: () => <div aria-label="Egg avatar" />,
}));
vi.mock("../components/avatar/avatar-canvas", () => ({
  AvatarCanvas: () => <div />,
}));
afterEach(cleanup);
const deferred = () => {
  let resolve!: (reply: PreviewReply) => void;
  const promise = new Promise<PreviewReply>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};
function setup() {
  const updates: PreviewState[] = [];
  const audio = {
    play: vi.fn().mockResolvedValue(undefined),
    pause: vi.fn(),
    load: vi.fn(),
    removeAttribute: vi.fn(),
    onplaying: null,
    onpause: null,
    onended: null,
    onerror: null,
  } as unknown as HTMLAudioElement;
  const create = vi.fn(() => audio);
  const controller = new PreviewController((s) => updates.push(s), create);
  return { updates, audio, create, controller };
}
describe("single-turn Preview", () => {
  it("replaces the turn and fences stale responses", async () => {
    const { updates, controller } = setup();
    const first = deferred(),
      second = deferred();
    const a = controller.ask("old", () => first.promise),
      b = controller.ask("new", () => second.promise);
    second.resolve({ answer: "New answer." });
    await b;
    first.resolve({ answer: "Old answer." });
    await a;
    expect(updates.at(-1)).toEqual({
      question: "new",
      answer: "New answer.",
      playing: false,
    });
    expect(updates.map((s) => s.answer)).not.toContain("Old answer.");
  });
  it("shows the shared no-publication error in the existing caption", async () => {
    const request = vi.fn().mockRejectedValue({
      code: "agent_not_published",
      status: 409,
      details: { agent_name: "New Agent" },
    });
    render(<AgentPreview onClose={vi.fn()} request={request} />);
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
      target: { value: "Why?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(
      await screen.findByText(
        "Agent “New Agent” has no published version. Open it and press Done to publish it.",
      ),
    ).toBeTruthy();
    expect(request).toHaveBeenCalledOnce();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });
  it("moves the mouth only on real playing and closes on pause/end/error/Close", async () => {
    const { updates, audio, controller } = setup();
    await controller.ask("Hi", async () => ({
      answer: "Hello.",
      audio_base64: "YQ==",
      audio_content_type: "audio/wav",
    }));
    expect(updates.at(-1)?.playing).toBe(false);
    const playing = audio.onplaying!;
    playing.call(audio, new Event("playing"));
    expect(updates.at(-1)?.playing).toBe(true);
    for (const event of ["pause", "ended", "error"] as const) {
      await controller.ask("Hi", async () => ({
        answer: "Hello.",
        audio_base64: "YQ==",
        audio_content_type: "audio/wav",
      }));
      audio.onplaying!.call(audio, new Event("playing"));
      audio[`on${event}`]!.call(audio, new Event(event));
      expect(updates.at(-1)?.playing).toBe(false);
    }
    controller.close();
    expect(audio.pause).toHaveBeenCalled();
    expect(audio.removeAttribute).toHaveBeenCalledWith("src");
    playing.call(audio, new Event("playing"));
    expect(updates.at(-1)?.playing).toBe(false);
  });
  it("Close fences an in-flight reply and no Voice creates no audio", async () => {
    const { controller, create, updates } = setup();
    await controller.ask("a", async () => ({ answer: "A." }));
    expect(create).not.toHaveBeenCalled();
    const d = deferred();
    const request = controller.ask("b", () => d.promise);
    controller.close();
    d.resolve({
      answer: "Late.",
      audio_base64: "YQ==",
      audio_content_type: "audio/wav",
    });
    await request;
    expect(create).not.toHaveBeenCalled();
    expect(updates.at(-1)?.answer).toBe("");
  });
  it("new question stops audio and fences old media callbacks", async () => {
    const { controller, audio, updates } = setup();
    await controller.ask("a", async () => ({
      answer: "A.",
      audio_base64: "YQ==",
      audio_content_type: "audio/wav",
    }));
    const stale = audio.onplaying!;
    await controller.ask("b", async () => ({ answer: "B." }));
    stale.call(audio, new Event("playing"));
    expect(audio.pause).toHaveBeenCalled();
    expect(updates.at(-1)).toEqual({
      question: "b",
      answer: "B.",
      playing: false,
    });
  });
  it("fills the viewport and restores the page gutter and focus on Close", () => {
    document.documentElement.style.scrollbarGutter = "stable";
    const close = vi.fn();
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();
    const { unmount } = render(
      <AgentPreview
        onClose={close}
        request={async () => ({ answer: "One sentence." })}
      />,
    );
    expect(document.documentElement.style.scrollbarGutter).toBe("auto");
    expect(document.documentElement.style.overflow).toBe("hidden");
    expect(
      screen.getByRole("button", { name: "Send" }).getAttribute("disabled"),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(close).toHaveBeenCalledOnce();
    unmount();
    expect(document.documentElement.style.scrollbarGutter).toBe("stable");
    expect(document.documentElement.style.overflow).toBe("");
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
    document.documentElement.style.scrollbarGutter = "";
  });
  it("has exactly Close, latest caption/chip, input and Send", () => {
    const send = vi.fn();
    render(
      <PreviewControls
        question="Why?"
        answer="Because."
        onClose={vi.fn()}
        onSend={send}
      />,
    );
    expect(
      screen.getAllByRole("button").map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Close", "Send"]);
    expect(screen.getByText("Why?")).toBeTruthy();
    expect(screen.getByText("Because.")).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText("Type a message..."), {
      target: { value: "Next?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(send).toHaveBeenCalledWith("Next?");
  });
  it("Egg has only Preview; non-Egg has no content action and keeps customization", () => {
    const templates = [
      defaults["wave1-default-head"],
      defaults["maya-warm-scholar"],
      defaults["maya-civic-observer"],
      defaults.egg,
    ].map((c) => ({
      id: c.template_id,
      name: c.template_id,
      available: true,
      supported_parameters: [],
    }));
    const { rerender } = render(
      <AvatarEditor
        templates={templates}
        value={defaults.egg}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.getAllByRole("radio").map((b) => b.textContent)).toEqual([
      "Default",
      "Scholar",
      "Observer",
      "Egg",
    ]);
    rerender(
      <AvatarEditor
        templates={templates}
        value={defaults["wave1-default-head"]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
    expect(screen.getByLabelText("Material theme")).toBeTruthy();
  });
});
