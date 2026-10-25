import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  LlmParamsCard,
  defaultVoiceValues,
  voicePayload,
  type VoiceParamSpec,
} from "../components/debate/setup/llm-params-card";
import { LocaleProvider } from "../components/locale";

const voiceSpecs: VoiceParamSpec[] = [
  {
    name: "rate",
    kind: "float",
    default: 1.25,
    minimum: 0.5,
    maximum: 2,
    step: 0.05,
  },
  { name: "instruction", kind: "text", default: null, max_length: 500 },
  { name: "seed", kind: "int", default: null, minimum: 0, maximum: 65535 },
];

describe("voice parameters on the generation card", () => {
  it("starts from the server defaults and sends only what is set", () => {
    const values = defaultVoiceValues(voiceSpecs);
    expect(values).toEqual({ rate: 1.25, instruction: null, seed: null });
    expect(voicePayload(values)).toEqual({
      rate: 1.25,
      instruction: null,
      seed: null,
    });
    expect(
      voicePayload({
        rate: 1.1,
        instruction: "  语气坚定，像辩论赛选手 ",
        seed: 7,
      }),
    ).toEqual({ rate: 1.1, instruction: "语气坚定，像辩论赛选手", seed: 7 });
    expect(
      voicePayload({ rate: null, instruction: "   ", seed: null }),
    ).toEqual({
      rate: null,
      instruction: null,
      seed: null,
    });
  });

  it("shows rate, instruction and seed with ranges in their help", () => {
    const onVoiceChange = vi.fn();
    render(
      <LocaleProvider initialLocale="zh">
        <LlmParamsCard
          specs={[]}
          values={{} as never}
          voiceSpecs={voiceSpecs}
          voiceValues={{ rate: 1.25, instruction: null, seed: 42 }}
          onChange={vi.fn()}
          onVoiceChange={onVoiceChange}
          onReset={vi.fn()}
        />
      </LocaleProvider>,
    );
    expect(screen.getByRole("heading", { name: "语音" })).toBeTruthy();
    const rateHelp = screen.getByRole("button", { name: /^rate:/ });
    expect(rateHelp.getAttribute("data-ui-guide-text")).toContain("0.5 到 2.0");
    expect(rateHelp.getAttribute("data-ui-guide-text")).toContain("1.1–1.3");
    expect(
      screen
        .getByRole("button", { name: /^seed:/ })
        .getAttribute("data-ui-guide-text"),
    ).toContain("0 到 65535");

    fireEvent.change(screen.getByRole("slider", { name: "rate slider" }), {
      target: { value: "1.5" },
    });
    expect(onVoiceChange).toHaveBeenLastCalledWith("rate", 1.5);
    fireEvent.change(screen.getByRole("textbox", { name: "instruction" }), {
      target: { value: "语气坚定" },
    });
    expect(onVoiceChange).toHaveBeenLastCalledWith("instruction", "语气坚定");
    const seed = screen.getByRole("spinbutton", { name: "seed" });
    fireEvent.change(seed, { target: { value: "" } });
    expect(onVoiceChange).toHaveBeenLastCalledWith("seed", null);
  });
});
