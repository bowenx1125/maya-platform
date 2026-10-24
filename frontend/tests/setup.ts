import { configure } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetClientMetricsForTests } from "../lib/client-metrics";
import { resetPollPacing } from "../lib/poll-pacing";

configure({ asyncUtilTimeout: 5_000 });

// A busy signal in one test must not slow the polls of the next.
afterEach(() => resetPollPacing());

// Sampling is random per page load; tests opt in explicitly.
resetClientMetricsForTests(false);
afterEach(() => resetClientMetricsForTests(false));
