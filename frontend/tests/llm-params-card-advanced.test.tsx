import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DebateLLMDefaults } from "../lib/api";
import {
  LlmParamsCard,
  defaultParamValues,
  paramsPayload,
} from "../components/debate/setup/llm-params-card";

// The shape GET /courses/{id}/debate-llm-defaults returns (generation_params.py).
const serverSpecs: DebateLLMDefaults["params"] = [
  {
    name: "temperature",
    kind: "float",
    default: 0.7,
    minimum: 0,
    maximum: 2,
    exclusive_minimum: false,
    exclusive_maximum: true,
    step: 0.05,
    sent: true,
  },
  {
    name: "top_p",
    kind: "float",
    default: null,
    minimum: 0,
    maximum: 1,
    exclusive_minimum: true,
    exclusive_maximum: false,
    step: 0.05,
    sent: true,
  },
  {
    name: "presence_penalty",
    kind: "float",
    default: null,
    minimum: -2,
    maximum: 2,
    exclusive_minimum: false,
    exclusive_maximum: false,
    step: 0.1,
    sent: true,
  },
  {
    name: "frequency_penalty",
    kind: "float",
    default: 0.2,
    minimum: -2,
    maximum: 2,
    exclusive_minimum: false,
    exclusive_maximum: false,
    step: 0.1,
    sent: false,
  },
  {
    name: "repetition_penalty",
    kind: "float",
    default: null,
    minimum: 0,
    maximum: 2,
    exclusive_minimum: true,
    exclusive_maximum: false,
    step: 0.01,
    sent: true,
  },
  {
    name: "max_tokens",
    kind: "int",
    default: 4096,
    minimum: 1,
    maximum: 32768,
    exclusive_minimum: false,
    exclusive_maximum: false,
    sent: true,
  },
  {
    name: "enable_thinking",
    kind: "bool",
    default: false,
    exclusive_minimum: false,
    exclusive_maximum: false,
    sent: true,
  },
  {
    name: "seed",
    kind: "int",
    default: null,
    minimum: 0,
    maximum: 2147483647,
    exclusive_minimum: false,
    exclusive_maximum: false,
    sent: true,
  },
];

describe("generation parameter card", () => {
  it("never holds or sends frequency_penalty or max_tokens, even with env defaults", () => {
    const values = defaultParamValues(serverSpecs);
    expect(Object.keys(values).sort()).toEqual(
      [
        "enable_thinking",
        "presence_penalty",
        "repetition_penalty",
        "seed",
        "temperature",
        "top_p",
      ].sort(),
    );
    expect(paramsPayload(values)).toEqual({
      temperature: 0.7,
      top_p: null,
      presence_penalty: null,
      repetition_penalty: null,
      enable_thinking: false,
      seed: null,
    });
  });

  it("shows temperature and folds the other parameters into a collapsed Advanced section", () => {
    const onChange = vi.fn();
    const onReset = vi.fn();
    render(
      <LlmParamsCard
        specs={serverSpecs}
        values={defaultParamValues(serverSpecs)}
        onChange={onChange}
        onReset={onReset}
      />,
    );
    const visible = () =>
      Array.from(document.querySelectorAll("[data-param]")).map((row) =>
        row.getAttribute("data-param"),
      );
    expect(visible()).toEqual(["temperature"]);
    expect(screen.queryByText("frequency_penalty")).toBeNull();
    expect(screen.queryByText("max_tokens")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Advanced" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(
      screen
        .getByRole("button", { name: /^temperature:/ })
        .getAttribute("data-ui-guide-text"),
    ).toContain("0 到 2");

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(visible()).toEqual([
      "temperature",
      "top_p",
      "presence_penalty",
      "repetition_penalty",
      "enable_thinking",
      "seed",
    ]);
    const advanced = document.getElementById(
      toggle.getAttribute("aria-controls") ?? "",
    );
    expect(advanced).toBeTruthy();
    expect(
      within(advanced as HTMLElement)
        .getByRole("button", { name: /^top_p:/ })
        .getAttribute("data-ui-guide-hover"),
    ).toBe("true");
    expect(screen.queryByText("frequency_penalty")).toBeNull();
    expect(screen.queryByText("max_tokens")).toBeNull();

    // The folded rows keep their behaviour: an omitted float is switched on
    // with its send toggle, and an empty seed means not sent.
    fireEvent.click(
      within(
        (advanced as HTMLElement).querySelector(
          '[data-param="top_p"]',
        ) as HTMLElement,
      ).getByRole("checkbox"),
    );
    expect(onChange).toHaveBeenLastCalledWith("top_p", {
      value: 0.8,
      send: true,
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "seed" }), {
      target: { value: "42" },
    });
    expect(onChange).toHaveBeenLastCalledWith("seed", {
      value: 42,
      send: true,
    });

    fireEvent.click(toggle);
    expect(visible()).toEqual(["temperature"]);
    fireEvent.click(screen.getByRole("button", { name: "Restore defaults" }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
