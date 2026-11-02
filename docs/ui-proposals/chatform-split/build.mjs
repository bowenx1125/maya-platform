import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));

const people = {
  socrates: {
    name: "Socrates",
    fill: "#c2704f",
    tone: "#f2b79a",
    shape: "arch",
  },
  mencius: {
    name: "Mencius",
    fill: "#8f7bb5",
    tone: "#c9d3f0",
    shape: "block",
  },
  hypatia: {
    name: "Hypatia",
    fill: "#6f9b7d",
    tone: "#c9d9a0",
    shape: "round",
  },
  ada: {
    name: "Ada Lovelace",
    fill: "#b9a06a",
    tone: "#e7e1d4",
    shape: "pillar",
  },
};

function scholar(id, className = "scholar") {
  const p = people[id];
  const body =
    p.shape === "round"
      ? `<circle cx="32" cy="36" r="22" fill="${p.fill}"/>`
      : p.shape === "pillar"
        ? `<rect x="20" y="8" width="24" height="60" rx="12" fill="${p.fill}"/>`
        : p.shape === "arch"
          ? `<path d="M14 66 V32 a18 18 0 0 1 36 0 V66 Z" fill="${p.fill}"/>`
          : `<rect x="12" y="16" width="40" height="50" rx="8" fill="${p.fill}"/>`;
  return `<svg class="${className}" viewBox="0 0 64 78" aria-hidden="true">${body}<circle cx="26" cy="34" r="2.2" fill="#111"/><circle cx="38" cy="34" r="2.2" fill="#111"/><path d="M27 44 q5 5 10 0" fill="none" stroke="#111" stroke-width="1.8" stroke-linecap="round"/></svg>`;
}

const chevron = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>`;
const check = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>`;

function sidebar(active) {
  const item = (key, label) =>
    `<li class="${key === active ? "on" : ""}">${label}</li>`;
  return `<aside class="side">
    <div class="brand"><i></i>Mayaform</div>
    <section class="group">
      <h2><span class="swatch" style="background:#a3e635"></span>Studyform</h2>
      <ul style="border-color:#a3e635">
        ${item("agents", "Agents")}
        ${item("teams", "Teams")}
      </ul>
    </section>
    <section class="group">
      <h2><span class="swatch" style="background:#67e8f9"></span>Brainform</h2>
      <ul style="border-color:#67e8f9">
        ${item("rag", "RAG")}
        ${item("voices", "Voices")}
        ${item("record", "Record")}
        ${item("knowledge", "Knowledge")}
      </ul>
    </section>
    <section class="group">
      <h2><span class="swatch" style="background:#fdba74"></span>Chatform</h2>
      <ul style="border-color:#fdba74">
        ${item("agent", "Chat with Agent")}
        ${item("team", "Chat with Team")}
      </ul>
    </section>
    <section class="group">
      <h2><span class="swatch" style="background:#fff"></span>Classroom</h2>
      <ul>
        ${item("debates", "Debates")}
        ${item("accounts", "Accounts")}
      </ul>
    </section>
    <div class="side-foot">
      <div>Meet Problems?<br /><span>Send to t330034059@mail.bnbu.edu.cn</span></div>
      <div>Logout</div>
    </div>
    <span class="collapse" aria-hidden="true">‹</span>
  </aside>`;
}

function page({ plan, title, active, body }) {
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>${title}</title>
    <link rel="stylesheet" href="mockup.css" />
  </head>
  <body class="plan-${plan}">
    <div class="app">
      ${sidebar(active)}
      <main class="main">${body}</main>
    </div>
    <footer class="stamp">
      <span><b>${title}</b></span>
      <span>EXAMPLE DATA · 示例数据，不是真实会话</span>
    </footer>
  </body>
</html>
`;
}

const agents = [
  { id: "socrates", version: "V1.3", visibility: "Public", picked: true },
  { id: "mencius", version: "V1.1", visibility: "Private" },
  { id: "hypatia", version: "V2.0", visibility: "Public" },
  {
    id: "ada",
    version: "V1.4",
    visibility: "Public",
    unavailable: true,
  },
];

const teams = [
  {
    id: "reason",
    name: "Reasoning circle",
    version: "V1.2",
    visibility: "Public",
    tone: "#f2b79a",
    leader: "socrates",
    members: ["socrates", "mencius", "hypatia", "ada"],
    picked: true,
  },
  {
    id: "pod",
    name: "Study pod",
    version: "V1.0",
    visibility: "Private",
    tone: "#c9d3f0",
    leader: "ada",
    members: ["ada", "hypatia"],
  },
  {
    id: "seminar",
    name: "Seminar table",
    version: "V1.5",
    visibility: "Public",
    tone: "#c9d9a0",
    leader: "hypatia",
    members: ["hypatia", "mencius", "socrates"],
  },
];

function banner(kind, heading) {
  return `<header class="banner">
    <div>
      <span class="kind-sticker ${kind === "Team" ? "team" : ""}">${kind} chat</span>
      <h1>${heading}</h1>
    </div>
    <div class="actions">
      <button class="pa" type="button">${chevron} Back</button>
      <button class="pa done" type="button">${check} Done</button>
    </div>
  </header>`;
}

function planAAgent() {
  const cards = agents
    .map((agent) => {
      const person = people[agent.id];
      return `<button class="sticker${agent.picked ? " picked" : ""}${agent.unavailable ? " unavailable" : ""}" type="button" style="--tone:${person.tone}" aria-pressed="${agent.picked ? "true" : "false"}">
        <span class="ver">${agent.version}</span>
        <span class="tape">${person.name}</span>
        <span class="sun">${scholar(agent.id)}</span>
        <span class="card-meta">
          <span class="vis ${agent.visibility === "Public" ? "public" : "private"}">${agent.visibility}</span>
          <span class="vis ${agent.unavailable ? "off" : "public"}">${agent.unavailable ? "Unavailable" : "Available"}</span>
        </span>
        ${agent.picked ? `<span class="mark">✓</span>` : ""}
      </button>`;
    })
    .join("");
  return `${banner("Agent", "New Agent chat")}
    <p class="hint">Pick one Agent. Done opens an Agent chat. Teams stay on Chat with Team.</p>
    <div class="sticker-grid">${cards}</div>`;
}

function planATeam() {
  const cards = teams
    .map((team) => {
      const faces = team.members
        .slice(0, 4)
        .map((id) => scholar(id))
        .join("");
      const names = team.members.map((id) => people[id].name).join(", ");
      return `<button class="team-card${team.picked ? " picked" : ""}" type="button" aria-pressed="${team.picked ? "true" : "false"}">
        <span class="ver">${team.version}</span>
        <span class="tape">${team.name}</span>
        <span class="faces" style="--tone:${team.tone}">${faces}</span>
        <span class="card-meta">
          <span class="vis ${team.visibility === "Public" ? "public" : "private"}">${team.visibility}</span>
          <span class="vis off">${team.members.length} members</span>
        </span>
        <span class="roster">
          <span><b>Leader</b> ${people[team.leader].name}</span>
          <span class="muted">${names}</span>
        </span>
        ${team.picked ? `<span class="mark">✓</span>` : ""}
      </button>`;
    })
    .join("");
  return `${banner("Team", "New Team chat")}
    <p class="hint">Pick one Team. Done opens a Team chat. Agents stay on Chat with Agent.</p>
    <div class="team-grid">${cards}</div>`;
}

const reply = `<p>Courage, in this reading, is not one brave moment. It is the habit of choosing the harder right when stopping would be easier.</p>
<p>The seminar notes put the same idea next to practice. You become steady by repeating the hard thing, not by waiting to feel ready.</p>`;

const replyShort = `<p>Courage, in this reading, is not one brave moment. It is the habit of choosing the harder right when stopping would be easier.</p>`;

function historyRows() {
  const rows = [
    ["socrates", "Courage and habit", "Agent", "Nov 2", true],
    ["mencius", "Office hours", "Agent", "Oct 28", false],
    ["hypatia", "Reasoning circle", "Team", "Oct 21", false],
    ["ada", "Draft notes", "Agent", "Oct 18", false],
  ];
  return rows
    .map(
      ([
        id,
        title,
        kind,
        date,
        current,
      ]) => `<div class="hrow${current ? " current" : ""}">
        <span class="mini" style="--tone:${people[id].tone}">${scholar(id)}</span>
        <span class="hcopy"><strong>${title}</strong><span class="chip ${kind === "Team" ? "team" : ""}">${kind}</span></span>
        <span class="hdate">${date}</span>
      </div>`,
    )
    .join("");
}

function ragBlock(open) {
  if (!open) {
    return `<div class="rag">
      <div class="rag-sum">Check RAG <span class="count">2</span></div>
      <div class="file-pills"><span>ethics-week-3.pdf</span><span>seminar-notes.md</span></div>
    </div>`;
  }
  return `<div class="rag">
    <div class="rag-sum">Check RAG <span class="count">2</span> <span class="chev">sources open</span></div>
    <article class="src">
      <header><span class="src-name">ethics-week-3.pdf</span><span class="k">EXCERPT</span></header>
      <p>Courage is the habit of choosing the harder right when fear makes the easier wrong look reasonable. It is trained, not bestowed.</p>
    </article>
    <article class="src">
      <header><span class="src-name">seminar-notes.md</span><span class="chev">Show excerpt</span></header>
    </article>
  </div>`;
}

function planAChat(open) {
  return `<header class="banner">
      <div>
        <span class="kind-sticker">Agent chat</span>
        <h1>Chatform</h1>
      </div>
      <div class="actions"><button class="pa done" type="button">+ New</button></div>
    </header>
    <div class="chat-shell">
      <aside class="hist">
        <div class="hist-tape">History</div>
        ${historyRows()}
      </aside>
      <section class="thread">
        <header class="thread-head">
          <span class="peek" style="--tone:${people.socrates.tone}">${scholar("socrates")}</span>
          <span class="title-tape">Courage and habit</span>
          <span class="chip">Agent</span>
        </header>
        <div class="msgs">
          <div class="user">What did the reading say about courage and habit?</div>
          <div class="bubble">
            <span class="mini" style="--tone:${people.socrates.tone}">${scholar("socrates")}</span>
            <div class="reply">${open ? replyShort : reply}${ragBlock(open)}</div>
          </div>
        </div>
        <div class="composer">
          <button class="plus" type="button" aria-label="Add attachment">+</button>
          <p>Message Socrates</p>
          <button class="send" type="button" aria-label="Send">↑</button>
        </div>
      </section>
    </div>`;
}

function bHead(kicker, heading) {
  return `<header class="b-head">
    <div>
      <p class="b-kicker">${kicker}</p>
      <h1>${heading}</h1>
    </div>
    <div class="b-actions">
      <button class="ghost" type="button">Back</button>
      <button class="solid" type="button">Done</button>
    </div>
  </header>`;
}

function planBAgent() {
  const rows = agents
    .map((agent) => {
      const person = people[agent.id];
      return `<button class="row${agent.picked ? " on" : ""}${agent.unavailable ? " off" : ""}" type="button">
        <span class="av" style="--tone:${person.tone}">${scholar(agent.id)}</span>
        <span>
          <h3>${person.name}</h3>
          <div class="sub">${agent.visibility} · ${agent.version}${agent.unavailable ? " · Unavailable" : ""}</div>
        </span>
        <span class="radio" aria-hidden="true"></span>
      </button>`;
    })
    .join("");
  return `${bHead("CHATFORM · AGENT SESSION", "New Agent chat")}
    <div class="search">Search Agents</div>
    <div class="rows">${rows}</div>`;
}

function planBTeam() {
  const rows = teams
    .map((team) => {
      const faces = team.members
        .map(
          (id) =>
            `<span class="av" style="--tone:${people[id].tone}">${scholar(id)}</span>`,
        )
        .join("");
      const pills = team.members
        .map((id) => {
          const lead = id === team.leader ? " lead" : "";
          const label =
            id === team.leader
              ? `${people[id].name} · Leader`
              : people[id].name;
          return `<span class="${lead.trim()}">${label}</span>`;
        })
        .join("");
      return `<button class="row${team.picked ? " on" : ""}" type="button">
        <span class="faces-soft">${faces}</span>
        <span>
          <h3>${team.name}</h3>
          <div class="sub">${team.visibility} · ${team.version} · ${team.members.length} members</div>
          <div class="member-pills">${pills}</div>
        </span>
        <span class="radio" aria-hidden="true"></span>
      </button>`;
    })
    .join("");
  return `${bHead("CHATFORM · TEAM SESSION", "New Team chat")}
    <div class="search">Search Teams</div>
    <div class="rows">${rows}</div>`;
}

function planBChat(open) {
  const sources = open
    ? `<div class="rag">
        <div class="rag-sum">CHECK RAG <span class="count">2</span></div>
        <article class="src">
          <header><span class="src-name">ethics-week-3.pdf</span><span class="k">Excerpt</span></header>
          <p>Courage is the habit of choosing the harder right when fear makes the easier wrong look reasonable. It is trained, not bestowed.</p>
        </article>
        <article class="src shut">
          <header><span class="src-name">seminar-notes.md</span><span class="k">Excerpt hidden</span></header>
        </article>
      </div>`
    : `<div class="rag">
        <div class="rag-sum">CHECK RAG <span class="count">2</span></div>
        <div class="file-pills"><span>ethics-week-3.pdf</span><span>seminar-notes.md</span></div>
      </div>`;
  return `<header class="b-head">
      <div>
        <p class="b-kicker">CHATFORM · AGENT SESSION</p>
        <h1>Courage and habit</h1>
      </div>
      <div class="b-actions"><button class="solid" type="button">New</button></div>
    </header>
    <div class="chat-shell">
      <aside class="hist">
        <div class="hist-tape">HISTORY</div>
        ${historyRows()}
      </aside>
      <section class="thread">
        <header class="thread-head">
          <span class="peek" style="--tone:${people.socrates.tone}">${scholar("socrates")}</span>
          <span class="title-tape">Socrates</span>
          <span class="chip">Agent</span>
        </header>
        <div class="msgs">
          <div class="user">What did the reading say about courage and habit?</div>
          <div class="bubble">
            <div class="reply">${open ? replyShort : reply}${sources}</div>
          </div>
        </div>
        <div class="composer">
          <button class="plus" type="button" aria-label="Add attachment">+</button>
          <p>Message Socrates</p>
          <button class="send" type="button" aria-label="Send">↑</button>
        </div>
      </section>
    </div>`;
}

function planCAgent() {
  const lines = agents
    .map((agent) => {
      const person = people[agent.id];
      return `<button class="pick-line${agent.picked ? " on" : ""}${agent.unavailable ? " off" : ""}" type="button">
        <span class="av" style="--tone:${person.tone}">${scholar(agent.id)}</span>
        <span><strong>${person.name}</strong><em>${agent.visibility} · ${agent.version}</em></span>
        <em>${agent.unavailable ? "Unavailable" : agent.picked ? "Selected" : ""}</em>
      </button>`;
    })
    .join("");
  return `<div class="stage">
    <section class="poster">
      <div class="eye">SESSION · AGENT</div>
      <h1>Socrates</h1>
      <div class="facts">
        <div><span>VISIBILITY</span><b>Public</b></div>
        <div><span>VERSION</span><b>V1.3</b></div>
        <div><span>STATUS</span><b>Available</b></div>
      </div>
      <div class="poster-art">${scholar("socrates")}</div>
      <div class="done-row">
        <button class="back-link" type="button">Back</button>
        <button class="big-done" type="button">Done · start Agent chat</button>
      </div>
    </section>
    <section class="list-pane">
      <h2>AGENTS</h2>
      ${lines}
    </section>
  </div>`;
}

function planCTeam() {
  const lines = teams
    .map((team) => {
      return `<button class="pick-line${team.picked ? " on" : ""}" type="button">
        <span class="av" style="--tone:${team.tone}">${scholar(team.leader)}</span>
        <span><strong>${team.name}</strong><em>${team.visibility} · ${team.version}</em></span>
        <em>${team.picked ? "Selected" : `${team.members.length}`}</em>
      </button>`;
    })
    .join("");
  const who = (id, lead) =>
    `<div class="who${lead ? " lead" : ""}"><span class="av" style="--tone:${people[id].tone}">${scholar(id)}</span>${people[id].name}${lead ? " · Leader" : ""}</div>`;
  return `<div class="stage">
    <section class="poster">
      <div class="eye">SESSION · TEAM</div>
      <h1>Reasoning circle</h1>
      <div class="facts">
        <div><span>VISIBILITY</span><b>Public</b></div>
        <div><span>VERSION</span><b>V1.2</b></div>
        <div><span>MEMBERS</span><b>4</b></div>
      </div>
      <div class="roster-block">
        <h3>ROSTER</h3>
        ${who("socrates", true)}
        ${who("mencius", false)}
        ${who("hypatia", false)}
        ${who("ada", false)}
      </div>
      <div class="done-row">
        <button class="back-link" type="button">Back</button>
        <button class="big-done" type="button">Done · start Team chat</button>
      </div>
    </section>
    <section class="list-pane">
      <h2>TEAMS</h2>
      ${lines}
    </section>
  </div>`;
}

function planCChat(open) {
  const drawer = open
    ? `<aside class="drawer open">
        <h2>CHECK RAG</h2>
        <p class="note">Filename and excerpt from ChatSource. The numbers are a proposed link into the reply. Chat sources have no text spans today.</p>
        <article class="d-card on">
          <header><span class="n">1</span><strong>ethics-week-3.pdf</strong></header>
          <p>Courage is the habit of choosing the harder right when fear makes the easier wrong look reasonable. It is trained, not bestowed.</p>
        </article>
        <article class="d-card">
          <header><span class="n">2</span><strong>seminar-notes.md</strong></header>
          <div class="shut">Excerpt collapsed</div>
        </article>
      </aside>`
    : `<aside class="drawer"><div class="drawer-tab">CHECK RAG · 2</div></aside>`;
  const marked = `<p>Courage, in this reading, is not one brave moment. It is the habit of choosing the harder right when stopping would be easier. <span class="cite">1</span></p>
    <p>The seminar notes put the same idea next to practice. You become steady by repeating the hard thing, not by waiting to feel ready. <span class="cite">2</span></p>`;
  return `<div class="c-chat" style="--drawer:${open ? "340px" : "56px"}">
    <aside class="rail">
      <span class="mini on" style="--tone:${people.socrates.tone}">${scholar("socrates")}</span>
      <span class="mini" style="--tone:${people.mencius.tone}">${scholar("mencius")}</span>
      <span class="mini" style="--tone:${people.hypatia.tone}">${scholar("hypatia")}</span>
      <span class="mini" style="--tone:${people.ada.tone}">${scholar("ada")}</span>
    </aside>
    <section class="c-thread">
      <div class="c-top">
        <h1>Courage and habit</h1>
        <span>AGENT · SOCRATES</span>
      </div>
      <div class="c-msgs">
        <div class="c-user">What did the reading say about courage and habit?</div>
        <div class="c-agent">${open ? marked : marked}</div>
      </div>
      <div class="c-compose">
        <p>Message Socrates</p>
        <button type="button" aria-label="Send">↑</button>
      </div>
    </section>
    ${drawer}
  </div>`;
}

const screens = [
  [
    "planA-agent-create.html",
    "plan-a",
    "PLAN A · New Agent chat",
    "agent",
    planAAgent(),
  ],
  [
    "planA-team-create.html",
    "plan-a",
    "PLAN A · New Team chat",
    "team",
    planATeam(),
  ],
  [
    "planA-chat.html",
    "plan-a",
    "PLAN A · Chat · 18px",
    "agent",
    planAChat(false),
  ],
  ["planA-rag.html", "plan-a", "PLAN A · Check RAG", "agent", planAChat(true)],
  [
    "planB-agent-create.html",
    "plan-b",
    "PLAN B · New Agent chat",
    "agent",
    planBAgent(),
  ],
  [
    "planB-team-create.html",
    "plan-b",
    "PLAN B · New Team chat",
    "team",
    planBTeam(),
  ],
  [
    "planB-chat.html",
    "plan-b",
    "PLAN B · Chat · 19px",
    "agent",
    planBChat(false),
  ],
  ["planB-rag.html", "plan-b", "PLAN B · Check RAG", "agent", planBChat(true)],
  [
    "planC-agent-create.html",
    "plan-c",
    "PLAN C · New Agent chat",
    "agent",
    planCAgent(),
  ],
  [
    "planC-team-create.html",
    "plan-c",
    "PLAN C · New Team chat",
    "team",
    planCTeam(),
  ],
  [
    "planC-chat.html",
    "plan-c",
    "PLAN C · Chat · 20px",
    "agent",
    planCChat(false),
  ],
  ["planC-rag.html", "plan-c", "PLAN C · Check RAG", "agent", planCChat(true)],
];

for (const [file, planClass, title, active, body] of screens) {
  const plan = planClass.slice(-1);
  const html = page({ plan, title, active, body });
  writeFileSync(resolve(root, file), html);
}

const index = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Chatform design proposals</title>
    <link rel="stylesheet" href="mockup.css" />
  </head>
  <body class="plan-b">
    <main class="main">
      <header class="b-head">
        <div>
          <p class="b-kicker">DESIGN ONLY · DO NOT MERGE</p>
          <h1>Chatform proposals</h1>
        </div>
      </header>
      <div class="rows">
        ${screens
          .map(
            ([file, , title]) =>
              `<a class="row on" href="${file}"><span><h3>${title}</h3><div class="sub">${file}</div></span></a>`,
          )
          .join("")}
      </div>
    </main>
  </body>
</html>
`;
writeFileSync(resolve(root, "index.html"), index);
mkdirSync(resolve(root, "fonts"), { recursive: true });
console.log(`wrote ${screens.length} screens`);
