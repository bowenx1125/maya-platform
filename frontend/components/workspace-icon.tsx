export type WorkspaceIconName =
  | "home"
  | "classroom"
  | "accounts"
  | "quiz"
  | "knowledge"
  | "brain"
  | "voice"
  | "mic"
  | "chat"
  | "live"
  | "new"
  | "back"
  | "done"
  | "logout"
  | "agent"
  | "team"
  | "file"
  | "clock"
  | "chatTeam"
  | "mail"
  | "menu"
  | "pin"
  | "music"
  | "pause"
  | "play"
  | "next"
  | "stop"
  | "replay"
  | "interact"
  | "chevronLeft"
  | "chevronRight";

const paths: Record<WorkspaceIconName, string> = {
  home: "M3 10 12 3l9 7M5 9v11h5v-6h4v6h5V9",
  classroom: "M4 4h16v12H4zM8 21l4-5 4 5M8 8h8M8 12h5",
  quiz: "M8 4h8a2 2 0 0 1 2 2v14l-6-3-6 3V6a2 2 0 0 1 2-2ZM9 9h6M9 13h4",
  accounts:
    "M9 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-2a7 7 0 0 1 14 0v2M17 5a4 4 0 0 1 0 7M19 15a6 6 0 0 1 3 5v1",
  knowledge:
    "M12 7a3 3 0 0 0-3-3H3v15h5a4 4 0 0 1 4 2V7Zm0 0a3 3 0 0 1 3-3h6v15h-5a4 4 0 0 0-4 2",
  brain:
    "M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18ZM12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18ZM15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4",
  voice: "M4 9v6m4-9v12m4-15v18m4-15v12m4-9v6",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3ZM5 11a7 7 0 0 0 14 0M12 18v3",
  chat: "M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 0 1-1-5 8 8 0 0 1 8-8h2a8 8 0 0 1 8 8ZM8 10h8M8 14h5",
  live: "M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0ZM10 8l6 4-6 4z",
  new: "M12 5v14M5 12h14",
  back: "M19 12H5m7-7-7 7 7 7",
  done: "m5 12 4 4L19 6",
  logout: "M9 4H4v16h5M9 12h12m-4-4 4 4-4 4",
  agent: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM5 21v-1a7 7 0 0 1 14 0v1",
  team: "M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM2 20v-1a6 6 0 0 1 10-4.5M12 20v-1a6 6 0 0 1 10-1v2",
  file: "M14 3H6v18h12V7l-4-4Zm0 0v4h4M9 13h6M9 17h6",
  clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
  chatTeam:
    "M17 9a6 6 0 0 1-6 6H7l-4 3 1-4a6 6 0 0 1 7-11 6 6 0 0 1 6 6ZM20 12a5 5 0 0 1 1 6l1 3-4-2h-4",
  mail: "M3 5h18v14H3zm0 0 9 7 9-7",
  menu: "M4 6h16M4 12h16M4 18h16",
  pin: "M12 17v5M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V17h14v-1.8a2 2 0 0 0-1.1-1.8l-1.8-.9a2 2 0 0 1-1.1-1.8V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1z",
  music:
    "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm12-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  pause: "M8 5v14M16 5v14",
  play: "M7 4.5v15l12-7.5z",
  next: "M5 12h14m-6-6 6 6-6 6",
  stop: "M6 6h12v12H6z",
  replay: "M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5",
  interact:
    "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2v2h-2zM18 14h2v2h-2zM14 18h2v2h-2zM18 18h2v2h-2z",
  chevronLeft: "m15 5-7 7 7 7",
  chevronRight: "m9 5 7 7-7 7",
};

export function WorkspaceIcon({
  name,
  size = 20,
  stroke = 1.65,
}: {
  name: WorkspaceIconName;
  size?: number;
  stroke?: number;
}) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
    >
      <path d={paths[name]} />
    </svg>
  );
}
