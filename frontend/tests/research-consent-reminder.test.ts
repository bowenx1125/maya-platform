import { beforeEach, describe, expect, it } from "vitest";

import {
  forgetResearchConsent,
  hashUsernameKey,
  rememberResearchConsent,
  RESEARCH_CONSENT_COPY_VERSION,
  RESEARCH_CONSENT_PDF_HREF,
  RESEARCH_CONSENT_REMINDER_KEY,
  shouldRestoreResearchConsent,
} from "../lib/research-consent-reminder";

describe("research consent reminder", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("exposes the static PDF path for the current copy version", () => {
    expect(RESEARCH_CONSENT_PDF_HREF).toBe(
      `/legal/${RESEARCH_CONSENT_COPY_VERSION}.pdf`,
    );
  });

  it("restores only for the same hashed username on this device", async () => {
    await rememberResearchConsent("Student01");
    expect(await shouldRestoreResearchConsent("student01")).toBe(true);
    expect(await shouldRestoreResearchConsent("otheruser")).toBe(false);
    const raw = window.localStorage.getItem(RESEARCH_CONSENT_REMINDER_KEY);
    expect(raw).toBeTruthy();
    expect(raw).not.toContain("student01");
    expect(await hashUsernameKey("Student01")).toMatch(/^[0-9a-f]{64}$/);
  });

  it("forgets a reminder on revoke without copying to another account", async () => {
    await rememberResearchConsent("alpha");
    await rememberResearchConsent("beta");
    await forgetResearchConsent("alpha");
    expect(await shouldRestoreResearchConsent("alpha")).toBe(false);
    expect(await shouldRestoreResearchConsent("beta")).toBe(true);
  });
});
