"use client";

import * as React from "react";
import type { ReactNode } from "react";

type ViewTransitionProps = {
  name?: string;
  share?: string;
  default?: string;
  children: ReactNode;
};

// The App Router runs React canary, which ships <ViewTransition>; the stable
// React the tests run against does not. There the boundary renders its
// children unchanged, which is also what a browser without the View
// Transitions API shows.
const Native = (
  React as unknown as {
    ViewTransition?: (props: ViewTransitionProps) => ReactNode;
  }
).ViewTransition;

export function ViewTransition(props: ViewTransitionProps) {
  return Native ? <Native {...props} /> : <>{props.children}</>;
}
