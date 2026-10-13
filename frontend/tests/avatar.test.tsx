import {
  act,
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
  avatarAssetUrlForTemplate,
  avatarDefaultConfigForTemplate,
} from "../components/avatar";

const rendererInstances: Array<{
  canvas: HTMLCanvasElement;
  dispose: ReturnType<typeof vi.fn>;
  setAsset: ReturnType<typeof vi.fn>;
  finishLoad: () => void;
  failLoad: (error: Error) => void;
}> = [];

vi.mock("../components/avatar/avatar-renderer", () => ({
  AvatarRenderer: class MockAvatarRenderer {
    readonly canvas: HTMLCanvasElement;
    readonly dispose = vi.fn();
    readonly setAsset = vi.fn();

    constructor(options: {
      canvas: HTMLCanvasElement;
      assetUrl?: string;
      onReady?: () => void;
      onError?: (error: Error) => void;
    }) {
      this.canvas = options.canvas;
      this.finishLoad = () => options.onReady?.();
      this.failLoad = (error) => options.onError?.(error);
      rendererInstances.push(this);
      if (options.assetUrl === "/avatars/missing.glb") {
        queueMicrotask(() =>
          this.failLoad(new Error("intentional test failure")),
        );
      }
    }

    readonly finishLoad: () => void;
    readonly failLoad: (error: Error) => void;

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

describe("registered avatar assets", () => {
  it("maps each catalog template to a distinct local GLB", () => {
    expect(avatarAssetUrlForTemplate("wave1-default-head")).toBe(
      "/avatars/female_1.glb",
    );
    expect(avatarAssetUrlForTemplate("maya-warm-scholar")).toBe(
      "/avatars/elder-scholar.glb",
    );
    expect(avatarAssetUrlForTemplate("maya-civic-observer")).toBe(
      "/avatars/noble-scholar.glb",
    );
    expect(
      new Set([
        avatarAssetUrlForTemplate("wave1-default-head"),
        avatarAssetUrlForTemplate("maya-warm-scholar"),
        avatarAssetUrlForTemplate("maya-civic-observer"),
      ]).size,
    ).toBe(3);
  });
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

    expect(screen.getByRole("radio", { name: /Default/i })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /Scholar/i })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /Unavailable/i })).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Scholar/i }));
    expect(onChange).toHaveBeenLastCalledWith({
      template_id: "maya-warm-scholar",
      material_theme: "warm_sand",
      eye_color: "brown",
      default_expression: "attentive",
      expression_strength: "medium",
      motion_style: "calm",
    });

    fireEvent.click(screen.getByRole("radio", { name: /Observer/i }));
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

  it("switches the local asset without recreating the WebGL renderer", async () => {
    const view = render(
      <AvatarCanvas config={config} assetUrl="/avatars/female_1.glb" />,
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const renderer = rendererInstances[0];

    view.rerender(
      <AvatarCanvas config={config} assetUrl="/avatars/elder-scholar.glb" />,
    );

    await waitFor(() =>
      expect(renderer.setAsset).toHaveBeenCalledWith(
        "/avatars/elder-scholar.glb",
      ),
    );
    expect(rendererInstances).toHaveLength(1);
    expect(renderer.dispose).not.toHaveBeenCalled();
  });

  it.each(["ready", "failed"] as const)(
    "resets a %s preview while its replacement asset loads",
    async (previousStatus) => {
      const onLoad = vi.fn();
      const onError = vi.fn();
      const view = render(
        <AvatarCanvas
          config={config}
          assetUrl="/avatars/female_1.glb"
          fallbackLabel="Kaikai"
          onLoad={onLoad}
          onError={onError}
        />,
      );
      await waitFor(() => expect(rendererInstances).toHaveLength(1));
      const renderer = rendererInstances[0];
      act(() => {
        if (previousStatus === "ready") renderer.finishLoad();
        else renderer.failLoad(new Error("first asset failed"));
      });
      const preview = screen.getByRole("img", { name: /Kaikai/ });
      expect(preview.getAttribute("data-avatar-status")).toBe(previousStatus);

      view.rerender(
        <AvatarCanvas
          config={config}
          assetUrl="/avatars/elder-scholar.glb"
          fallbackLabel="Kaikai"
          onLoad={onLoad}
          onError={onError}
        />,
      );

      expect(preview.getAttribute("data-avatar-status")).toBe("loading");
      expect(preview.querySelector("canvas")?.hidden).toBe(true);
      expect(screen.queryByText("Kaikai · static preview")).toBeNull();
      expect(renderer.setAsset).toHaveBeenCalledWith(
        "/avatars/elder-scholar.glb",
      );
      expect(rendererInstances).toHaveLength(1);
      expect(renderer.dispose).not.toHaveBeenCalled();
      act(() => renderer.finishLoad());
      expect(preview.getAttribute("data-avatar-status")).toBe("ready");
      expect(preview.querySelector("canvas")?.hidden).toBe(false);
      expect(onLoad).toHaveBeenCalledTimes(previousStatus === "ready" ? 2 : 1);
      expect(onError).toHaveBeenCalledTimes(
        previousStatus === "failed" ? 1 : 0,
      );
    },
  );

  it("reloads the preview when a missing asset becomes available again", async () => {
    const view = render(<AvatarCanvas config={config} />);
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const oldRenderer = rendererInstances[0];
    act(() => oldRenderer.finishLoad());
    view.rerender(<AvatarCanvas config={config} assetUrl="" />);
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "failed",
    );
    expect(oldRenderer.dispose).toHaveBeenCalledTimes(1);
    view.rerender(<AvatarCanvas config={config} />);
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "loading",
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(2));
    act(() => rendererInstances[1].finishLoad());
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "ready",
    );
  });

  it("resets a loaded preview when its framing changes", async () => {
    const view = render(<AvatarCanvas config={config} framing="head" />);
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const oldRenderer = rendererInstances[0];
    act(() => oldRenderer.finishLoad());
    view.rerender(<AvatarCanvas config={config} framing="full-body" />);
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "loading",
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(2));
    expect(oldRenderer.dispose).toHaveBeenCalledTimes(1);
    act(() => rendererInstances[1].finishLoad());
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "ready",
    );
  });

  it("keeps a loaded asset ready when only its appearance changes", async () => {
    const view = render(<AvatarCanvas config={config} />);
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const renderer = rendererInstances[0];
    act(() => renderer.finishLoad());
    view.rerender(
      <AvatarCanvas config={{ ...config, material_theme: "warm_sand" }} />,
    );
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "ready",
    );
    expect(rendererInstances).toHaveLength(1);
    expect(renderer.dispose).not.toHaveBeenCalled();
  });

  it("ignores callbacks from a disposed renderer while its replacement loads", async () => {
    const onLoad = vi.fn();
    const onError = vi.fn();
    const view = render(
      <AvatarCanvas
        config={config}
        framing="head"
        onLoad={onLoad}
        onError={onError}
      />,
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const oldRenderer = rendererInstances[0];
    view.rerender(
      <AvatarCanvas
        config={config}
        framing="full-body"
        onLoad={onLoad}
        onError={onError}
      />,
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(2));
    const currentRenderer = rendererInstances[1];
    expect(oldRenderer.dispose).toHaveBeenCalledTimes(1);
    act(() => {
      oldRenderer.finishLoad();
      oldRenderer.failLoad(new Error("late disposed error"));
    });
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "loading",
    );
    expect(onLoad).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    act(() => currentRenderer.finishLoad());
    expect(screen.getByRole("img").getAttribute("data-avatar-status")).toBe(
      "ready",
    );
    expect(onLoad).toHaveBeenCalledTimes(1);
    view.unmount();
    act(() => {
      currentRenderer.finishLoad();
      currentRenderer.failLoad(new Error("late unmounted error"));
    });
    expect(onLoad).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it("shows the fallback when a replacement asset fails to load", async () => {
    const view = render(
      <AvatarCanvas
        config={config}
        assetUrl="/avatars/female_1.glb"
        fallbackLabel="Kaikai"
      />,
    );
    await waitFor(() => expect(rendererInstances).toHaveLength(1));
    const renderer = rendererInstances[0];
    renderer.finishLoad();
    const canvas = screen.getByRole("img", { name: /Kaikai/ });
    await waitFor(() =>
      expect(canvas.getAttribute("data-avatar-status")).toBe("ready"),
    );

    view.rerender(
      <AvatarCanvas
        config={config}
        assetUrl="/avatars/missing.glb"
        fallbackLabel="Kaikai"
      />,
    );
    await waitFor(() =>
      expect(renderer.setAsset).toHaveBeenCalledWith("/avatars/missing.glb"),
    );
    renderer.failLoad(new Error("replacement asset failed"));

    await waitFor(() => {
      expect(screen.getByText("Kaikai · static preview")).toBeTruthy();
      expect(canvas.getAttribute("data-avatar-status")).toBe("failed");
    });
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
    expect(
      screen.getByRole("radiogroup", { name: "Avatar template" }),
    ).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Scholar" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Observer" })).toBeTruthy();
    expect(
      screen.getByRole("img", { name: /Avatar avatar preview/i }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Nod" })).toBeTruthy();
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
        fallbackLabel="Kaikai"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Kaikai · static preview")).toBeTruthy();
    });
  });

  it("disposes the renderer when the canvas unmounts", async () => {
    const view = render(<AvatarCanvas config={config} fallbackLabel="Bowen" />);
    await waitFor(() => expect(rendererInstances.length).toBe(1));
    const instance = rendererInstances[0];
    view.unmount();
    expect(instance.dispose).toHaveBeenCalledTimes(1);
  });

  it("keeps the next agent on a live canvas when the model switches", async () => {
    const view = render(
      <AvatarCanvas
        config={config}
        assetUrl="/avatars/female_1.glb"
        fallbackLabel="Bowen"
      />,
    );
    await waitFor(() => expect(rendererInstances.length).toBe(1));
    const first = rendererInstances[0];
    expect(first.canvas.isConnected).toBe(true);

    view.rerender(
      <AvatarCanvas
        config={{ ...config, template_id: "maya-warm-scholar" }}
        assetUrl="/avatars/elder-scholar.glb"
        fallbackLabel="Elder"
      />,
    );
    await waitFor(() =>
      expect(first.setAsset).toHaveBeenCalledWith("/avatars/elder-scholar.glb"),
    );
    expect(rendererInstances).toHaveLength(1);
    expect(first.dispose).not.toHaveBeenCalled();
    expect(first.canvas.isConnected).toBe(true);
  });
});
