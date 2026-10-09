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
  priority?: number;
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
  priority = 0,
}: WorkspaceActionOptions & { name: WorkspaceActionName }) {
  const registry = useContext(WorkspaceActionsContext);
  const owner = useId();
  // Registered in the same commit as the page, so the sidebar never shows the
  // previous page state's handler, form or disabled flag for a frame.
  useLayoutEffect(() => {
    return registry?.register(
      name,
      owner,
      { href, form, onClick, disabled },
      priority,
    );
  }, [registry, owner, name, href, form, onClick, disabled, priority]);
  return null;
}
