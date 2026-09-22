"use client";

import {
  createContext,
  useContext,
  useEffect,
  type Dispatch,
  type MouseEventHandler,
  type SetStateAction,
} from "react";

export type WorkspaceActionName = "new" | "back" | "done";
export type WorkspaceActionOptions = {
  href?: string;
  form?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement | HTMLButtonElement>;
  disabled?: boolean;
};
export type WorkspaceActions = Partial<
  Record<WorkspaceActionName, WorkspaceActionOptions>
>;

export const WorkspaceActionsContext = createContext<Dispatch<
  SetStateAction<WorkspaceActions>
> | null>(null);

/** Pages register their existing action; the shell owns its single visible button. */
export function WorkspaceAction({
  name,
  href,
  form,
  onClick,
  disabled,
}: WorkspaceActionOptions & { name: WorkspaceActionName }) {
  const setActions = useContext(WorkspaceActionsContext);
  useEffect(() => {
    setActions?.((current) => ({
      ...current,
      [name]: { href, form, onClick, disabled },
    }));
    return () =>
      setActions?.((current) => {
        const next = { ...current };
        delete next[name];
        return next;
      });
  }, [setActions, name, href, form, onClick, disabled]);
  return null;
}
