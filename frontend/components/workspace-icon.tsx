export type WorkspaceIconName =
  | "home"
  | "classroom"
  | "accounts"
  | "knowledge"
  | "brain"
  | "voice"
  | "chat"
  | "live"
  | "new"
  | "back"
  | "done"
  | "logout";

const paths: Record<WorkspaceIconName, string> = {
  home: "M3 10 12 3l9 7M5 9v11h5v-6h4v6h5V9",
  classroom: "M4 4h16v12H4zM8 21l4-5 4 5M8 8h8M8 12h5",
  accounts:
    "M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-2a7 7 0 0 1 14 0v2M17 5a4 4 0 0 1 0 7M19 15a6 6 0 0 1 3 5v1",
  knowledge:
    "M12 7a3 3 0 0 0-3-3H3v15h5a4 4 0 0 1 4 2V7Zm0 0a3 3 0 0 1 3-3h6v15h-5a4 4 0 0 0-4 2",
  brain:
    "M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18ZM12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18ZM15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4",
  voice: "M4 9v6m4-9v12m4-15v18m4-15v12m4-9v6",
  chat: "M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 0 1-1-5 8 8 0 0 1 8-8h2a8 8 0 0 1 8 8ZM8 10h8M8 14h5",
  live: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM10 8l6 4-6 4z",
  new: "M12 5v14M5 12h14",
  back: "M19 12H5m7-7-7 7 7 7",
  done: "m5 12 4 4L19 6",
  logout: "M9 4H4v16h5M9 12h12m-4-4 4 4-4 4",
};

export function WorkspaceIcon({ name }: { name: WorkspaceIconName }) {
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      <path d={paths[name]} />
    </svg>
  );
}
