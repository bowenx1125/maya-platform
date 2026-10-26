"use client";

import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  type MouseEventHandler,
} from "react";

export type WorkspaceActionName = "new" | "back" | "done";
export type WorkspaceActionOptions = {
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
  /** Work this action started is still running: the button shows a spinner. */
  busy?: boolean;
  priority?: number;
  /** "page": the page draws this control itself (the Agent banner), so the
      shell keeps the registration but skips its sidebar button. */
  placement?: "page";
};
export type WorkspaceActions = Partial<
  Record<WorkspaceActionName, WorkspaceActionOptions>
>;

export type WorkspaceActionRegistry = {
  register: (
    name: WorkspaceActionName,
    owner: string,
    options: WorkspaceActionOptions,
    priority: number,
  ) => () => void;
};

export const WorkspaceActionsContext =
  createContext<WorkspaceActionRegistry | null>(null);

/** Pages register their existing action; the shell owns its single visible button. */
export function WorkspaceAction({
  name,
  href,
  form,
  onClick,
  disabled,
  busy,
  priority = 0,
  placement,
}: WorkspaceActionOptions & { name: WorkspaceActionName }) {
  const registry = useContext(WorkspaceActionsContext);
  const owner = useId();
  // Registered in the same commit as the page, so the sidebar never shows the
  // previous page state's handler, form or disabled flag for a frame.
  useLayoutEffect(() => {
    return registry?.register(
      name,
      owner,
      { href, form, onClick, disabled: disabled || busy, busy, placement },
      priority,
    );
  }, [
    registry,
    owner,
    name,
    href,
    form,
    onClick,
    disabled,
    busy,
    priority,
    placement,
  ]);
  return null;
}
