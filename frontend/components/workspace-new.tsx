"use client";

import {
  createContext,
  useContext,
  useEffect,
  type Dispatch,
  type SetStateAction,
} from "react";

export type WorkspaceNewAction = {
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
};

export const WorkspaceNewContext = createContext<Dispatch<
  SetStateAction<WorkspaceNewAction | null>
> | null>(null);

/** Pages register their existing action; the shell owns its single visible button. */
export function WorkspaceNew({ href, onClick, disabled }: WorkspaceNewAction) {
  const setAction = useContext(WorkspaceNewContext);
  useEffect(() => {
    setAction?.({ href, onClick, disabled });
    return () => setAction?.(null);
  }, [setAction, href, onClick, disabled]);
  return null;
}
