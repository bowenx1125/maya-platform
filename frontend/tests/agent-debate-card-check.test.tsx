import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AgentDebateCardCheck } from "../components/agent-debate-card-check";

const card = {
  identity: "A stored philosopher",
  position: "Evidence comes first",
  reasoning: [],
  speaking_style: "Warm",
  voice_style: null,
  dropped: [],
};
afterEach(cleanup);

it("loads only on opening Check card and renders the stored response", async () => {
  const load = vi.fn(async () => ({ card_status: "ready" as const, card }));
  render(
    <AgentDebateCardCheck
      agentName="Ada"
      agentMd="# Template identity"
      load={load}
    />,
  );
  expect(load).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Check card"));
  expect(await screen.findByText("A stored philosopher")).toBeTruthy();
  expect(screen.getByText("Evidence comes first")).toBeTruthy();
  expect(screen.queryByText("Template identity")).toBeNull();
  fireEvent.click(screen.getByText("Check card"));
  expect(load).toHaveBeenCalledOnce();
});

it("refreshes a competing compiling claim until its stored card is terminal", async () => {
  const load = vi
    .fn()
    .mockResolvedValueOnce({ card_status: "compiling" })
    .mockResolvedValue({ card_status: "ready", card });
  render(
    <AgentDebateCardCheck
      agentName="Ada"
      agentMd="Plain persona"
      load={load}
    />,
  );
  fireEvent.click(screen.getByText("Check card"));
  await waitFor(
    () => expect(screen.getByText("A stored philosopher")).toBeTruthy(),
    { timeout: 2500 },
  );
  expect(load).toHaveBeenCalledTimes(2);
});

it("shows the existing approved fallback reason after an endpoint failure", async () => {
  const load = vi.fn(async () => {
    throw new Error("unavailable");
  });
  render(
    <AgentDebateCardCheck
      agentName="Ada"
      agentMd="Plain persona"
      load={load}
    />,
  );
  fireEvent.click(screen.getByText("Check card"));
  await waitFor(() =>
    expect(screen.queryByTestId("debate-card-status")).toBeNull(),
  );
  expect(screen.queryByText("unavailable")).toBeNull();
  expect(load).toHaveBeenCalledOnce();
});
