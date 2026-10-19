import { configure } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetPollPacing } from "../lib/poll-pacing";

configure({ asyncUtilTimeout: 5_000 });

// A busy signal in one test must not slow the polls of the next.
afterEach(() => resetPollPacing());
