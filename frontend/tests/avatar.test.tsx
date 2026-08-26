import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  AvatarConfig,
  AvatarState,
  AvatarTemplate,
} from "../components/avatar";
import {
  AvatarCanvas,
  AvatarEditor,
  avatarDefaultConfigForTemplate,
} from "../components/avatar";

const rendererInstances: Array<{
  dispose: ReturnType<typeof vi.fn>;
}> = [];

vi.mock("../components/avatar/avatar-renderer", () => ({
  AvatarRenderer: class MockAvatarRenderer {
    readonly dispose = vi.fn();

    constructor(options: {
      assetUrl?: string;
      onReady?: () => void;
      onError?: (error: Error) => void;
    }) {
      rendererInstances.push(this);
      if (options.assetUrl === "/avatars/missing.glb") {
        queueMicrotask(() =>
          options.onError?.(new Error("intentional test failure")),
        );
      }
    }

    setConfig(_config: AvatarConfig): void {
      return;
    }

    setState(_state: string): void {
      return;
    }
  },
}));

const config: AvatarConfig = {
  template_id: "wave1-default-head",
  material_theme: "demo",
  eye_color: null,
  default_expression: "neutral",
  expression_strength: "medium",
  motion_style: "calm",
};

const templates: AvatarTemplate[] = [
  {
    id: "wave1-default-head",
    name: "Wave 1 Default Head",
    available: true,
    supported_parameters: ["material_theme", "eye_color"],
  },
  {
    id: "maya-warm-scholar",
    name: "Maya Warm Scholar",
    available: true,
    supported_parameters: ["material_theme", "eye_color"],
  },
  {
    id: "maya-civic-observer",
    name: "Maya Civic Observer",
    available: true,
    supported_parameters: ["material_theme", "eye_color"],
  },
  {
    id: "unavailable-template",
    name: "Unavailable",
    available: false,
    supported_parameters: [],
  },
];

afterEach(() => {
  cleanup();
  rendererInstances.length = 0;
});

describe("M07 avatar editor boundary", () => {
  it("emits only stable AvatarConfig values through callbacks", () => {
    const onChange = vi.fn();
    const onPreviewStateChange = vi.fn();
    render(
      <AvatarEditor
        templates={templates}
        value={config}
        onChange={onChange}
        onPreviewStateChange={onPreviewStateChange}
        fallbackLabel="Bowen"
      />,
    );

    expect(
      screen.getByRole("radio", { name: /Wave 1 Default Head/i }),
    ).toBeTruthy();
    expect(
      screen.getByRole("radio", { name: /Maya Warm Scholar/i }),
    ).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Unavailable/i })).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Maya Warm Scholar/i }));
    expect(onChange).toHaveBeenLastCalledWith({
      template_id: "maya-warm-scholar",
      material_theme: "warm_sand",
      eye_color: "brown",
      default_expression: "attentive",
      expression_strength: "medium",
      motion_style: "calm",
    });

    fireEvent.click(
      screen.getByRole("radio", { name: /Maya Civic Observer/i }),
    );
    expect(onChange).toHaveBeenLastCalledWith({
      template_id: "maya-civic-observer",
      material_theme: "civic_olive",
      eye_color: "gray",
      default_expression: "serious_angry",
      expression_strength: "medium",
      motion_style: "active",
    });

    fireEvent.change(screen.getByLabelText("Material theme"), {
      target: { value: "warm_sand" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      ...config,
      material_theme: "warm_sand",
    });

    fireEvent.click(screen.getByRole("button", { name: "speaking" }));
    expect(onPreviewStateChange).toHaveBeenCalledWith("speaking");
  });

  it("updates the internal preview state when no preview callback is provided", () => {
    render(
      <AvatarEditor templates={templates} value={config} onChange={vi.fn()} />,
    );

    const speaking = screen.getByRole("button", { name: "speaking" });
    expect(speaking.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(speaking);
    expect(speaking.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("img").getAttribute("data-avatar-state")).toBe(
      "speaking",
    );
  });

  it("keeps preview state controlled when a parent owns it", () => {
    function ControlledEditor() {
      const [state, setState] = useState<AvatarState>("idle");
      return (
        <AvatarEditor
          templates={templates}
          value={config}
          onChange={vi.fn()}
          previewState={state}
          onPreviewStateChange={setState}
        />
      );
    }

    render(<ControlledEditor />);
    fireEvent.click(screen.getByRole("button", { name: "speaking" }));
    expect(
      screen
        .getByRole("button", { name: "speaking" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("fails closed for unavailable, unknown, or incompatible server entries", () => {
    expect(
      avatarDefaultConfigForTemplate({
        id: "unavailable-template",
        available: false,
      }),
    ).toBeNull();
    expect(
      avatarDefaultConfigForTemplate({
        id: "future-template",
        available: true,
      }),
    ).toBeNull();
    expect(
      avatarDefaultConfigForTemplate({
        id: "maya-civic-observer",
        available: true,
        default_config: {
          template_id: "maya-civic-observer",
          material_theme: "not-a-server-theme",
          eye_color: "gray",
          default_expression: "neutral",
          expression_strength: "medium",
          motion_style: "calm",
        },
      }),
    ).toBeNull();

    expect(
      avatarDefaultConfigForTemplate({
        id: "maya-civic-observer",
        available: true,
        default_config: {
          template_id: "maya-civic-observer",
          material_theme: "civic_olive",
          eye_color: null,
          default_expression: "neutral",
          expression_strength: "high",
          motion_style: "active",
          ignored_private_field: "must not reach the callback",
        },
      }),
    ).toEqual({
      template_id: "maya-civic-observer",
      material_theme: "civic_olive",
      eye_color: null,
      default_expression: "neutral",
      expression_strength: "high",
      motion_style: "active",
    });
  });

  it("keeps controls usable on mobile-sized layouts and labels the shared asset honestly", () => {
    render(
      <AvatarEditor templates={templates} value={config} onChange={vi.fn()} />,
    );
    expect(screen.getByText(/share one compatible head asset/i)).toBeTruthy();
    expect(
      screen.getByRole("img", { name: /Avatar avatar preview/i }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "nod yes" })).toBeTruthy();
  });
});

describe("M07 avatar canvas failure and cleanup boundary", () => {
  it("renders the static name fallback after an asset load failure", async () => {
    // The actual loader invokes this callback on an HTTP/decode failure. The
    // unit keeps that failure path deterministic without touching a network.
    render(
      <AvatarCanvas
        config={config}
        assetUrl="/avatars/missing.glb"
        fallbackLabel="KaiKai"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("KaiKai · static preview")).toBeTruthy();
    });
  });

  it("disposes the renderer when the canvas unmounts", async () => {
    const view = render(<AvatarCanvas config={config} fallbackLabel="Bowen" />);
    await waitFor(() => expect(rendererInstances.length).toBe(1));
    const instance = rendererInstances[0];
    view.unmount();
    expect(instance.dispose).toHaveBeenCalledTimes(1);
  });
});
