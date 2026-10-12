import { useMemo, useState, type ReactNode } from "react";

import {
  WorkspaceActionsContext,
  type WorkspaceActionName,
  type WorkspaceActionOptions,
  type WorkspaceActionRegistry,
} from "../components/workspace-actions";

// The sidebar's New, Back and Done, without the rest of the app shell.
export function SidebarActions({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<
    Partial<
      Record<
        WorkspaceActionName,
        { owner: string; options: WorkspaceActionOptions }
      >
    >
  >({});
  const registry = useMemo<WorkspaceActionRegistry>(
    () => ({
      register: (name, owner, options) => {
        setActions((current) => ({ ...current, [name]: { owner, options } }));
        return () =>
          setActions((current) => {
            if (current[name]?.owner !== owner) return current;
            const next = { ...current };
            delete next[name];
            return next;
          });
      },
    }),
    [],
  );
  const labels = { new: "New", back: "Back", done: "Done" } as const;
  return (
    <WorkspaceActionsContext.Provider value={registry}>
      <nav>
        {(["new", "back", "done"] as const).map((name) => {
          const action = actions[name];
          return action ? (
            <button
              key={name}
              type="button"
              disabled={action.options.disabled}
              onClick={action.options.onClick}
            >
              {labels[name]}
            </button>
          ) : null;
        })}
      </nav>
      {children}
    </WorkspaceActionsContext.Provider>
  );
}
