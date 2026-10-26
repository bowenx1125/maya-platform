// gen-real.mjs: same 3 schemes, but the app shell (sidebar / mobile top bar) is the REAL B-final markup
// cloned from the running app with computed styles inlined (src/real-shell/*, captured by pw/capsb.mjs; sidebar New removed).
// Outputs *-rs.png beside the originals (old files untouched) + audit dumps.
// Chatform shared page – 3 schemes x 5 states x 2 widths. Tailwind (browser build) only, no CSS files.
import { chromium } from "playwright";
import fs from "fs";
const R = "/workspace/maya-ui/proposals/chatform/";
const TW = fs.readFileSync(R + "src/tw.js", "utf8");
const img = (f) =>
  "data:image/png;base64," + fs.readFileSync(R + "src/" + f).toString("base64");
const M = [img("m4.png"), img("m1.png"), img("m2.png"), img("m3.png")];
const FONT = `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@800&family=Lexend:wght@400;500;700;800&display=swap">`;
const GRID =
  "bg-[#DCEBFF] bg-[linear-gradient(#CDDBEE_1px,transparent_1px),linear-gradient(90deg,#CDDBEE_1px,transparent_1px)] bg-[size:32px_32px]";
const SUN = (c) =>
  `background:${c};background-image:repeating-conic-gradient(from 0deg at 50% 70%,#ffffff66 0 10deg,transparent 10deg 20deg)`;
const ic = {
  chat: '<path d="M4 5h16v11H8l-4 4z"/>',
  team: '<path d="M3 6h12v8H7l-4 3zM17 9h4v9l-3-2h-6v-2"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  done: '<path d="M5 12l5 5 9-10"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  pin: '<path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  up: '<path d="M12 19V5m-7 7 7-7 7 7"/>',
  clip: '<path d="M12 5v14M5 12h14"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
};
const I = (n, s = 16) =>
  `<svg aria-hidden="true" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">${ic[n]}</svg>`;
// Shared Button (DESIGN-RULES motion: 0 6px 0, hover -2px, press translateY(6px))
const BTN = (label, icon, kind = "neutral", extra = "") =>
  `<button class="inline-flex items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] px-3.5 py-2 font-[Lexend] text-sm font-extrabold shadow-[0_6px_0_#111] transition hover:-translate-y-[2px] active:translate-y-[6px] active:shadow-none ${kind === "main" ? "bg-[#FF4D8D]" : kind === "dis" ? "bg-[#FFB3CE] text-[#111]/50" : "bg-white"} ${extra}">${I(icon)}${label}</button>`;
// --- Sidebar (B-final, unchanged; no New/Back/Done) ---
function sidebar() {
  const g = (t, c, items) =>
    `<div class="mt-4"><div class="flex items-center gap-1.5 text-[10px] font-extrabold tracking-widest"><span class="inline-block size-2 border-2 border-[#111] rounded-[2px]"></span>${t}</div><div class="ml-1 mt-1.5 border-l-[3px] pl-2 space-y-1" style="border-color:${c}">${items.map(([n, a]) => `<div class="rounded-md px-2.5 py-1.5 text-[13px] font-bold ${a ? "bg-[#FF4D8D] border-[3px] border-[#111] shadow-[3px_3px_0_#111]" : ""}">${n}</div>`).join("")}</div></div>`;
  return `<aside class="relative w-[240px] shrink-0 min-h-full bg-[#FFE14D] border-r-[3px] border-[#111] px-3 py-5 flex flex-col"><div class="font-[Bricolage_Grotesque] text-[15px] font-extrabold flex items-center gap-2"><span class="size-4 rounded-full bg-[#111] inline-block border-2 border-[#FF4D8D]"></span>Mayaform</div>
${g("STUDYFORM", "#A3E635", [["Agents"], ["Teams"]])}${g("BRAINFORM", "#67E8F9", [["RAG"], ["Voices"], ["Record"]])}${g("CHATFORM", "#FDBA74", [["Chat with Agent", 1], ["Chat with Team"]])}${g("CLASSROOM", "#111", [["Live"]])}
<div class="mt-auto space-y-3"><div class="rounded-md border-[3px] border-[#111] bg-white p-2 text-[11px] font-bold shadow-[3px_3px_0_#111]">Meet Problems?<br><span class="underline font-medium">Send to t330034059@mail.bnbu.edu.cn</span></div><div class="rounded-md border-[3px] border-[#111] bg-white p-2 text-[13px] font-bold shadow-[3px_3px_0_#111]">Logout</div></div>
<span class="absolute -right-[16px] top-[50%] size-7 rounded-full border-[3px] border-[#111] bg-white grid place-items-center text-xs font-black shadow-[0_3px_0_#111]" aria-label="Collapse sidebar">‹</span></aside>`;
}
const mtop = `<div class="h-12 bg-[#FFE14D] border-b-[3px] border-[#111] flex items-center px-3 relative"><span class="size-8 rounded-md border-[3px] border-[#111] bg-white grid place-items-center shadow-[2px_2px_0_#111]">${I("menu")}</span><span class="absolute left-1/2 -translate-x-1/2 font-[Bricolage_Grotesque] font-extrabold text-lg">Mayaform</span></div>`;
// --- data (English mock only) ---
const HIST = [
  ["AI and learning", "10/24/2026", 0, "Agent", 1],
  ["Socrates", "10/27/2026", 1, "Agent", 0],
  ["Debate Squad", "10/22/2026", 2, "Team", 0],
  ["Lab notes", "10/20/2026", 3, "Agent", 0],
];
const AG = [
  ["Socrates", "V1.0", 0, "#F2B79A"],
  ["Confucius", "V2.0", 1, "#C9D3F0"],
  ["Marie Curie", "V1.0", 2, "#C9D9A0"],
];
const TM = [
  ["Debate Squad", "V1.2", "#FDBA74", 4],
  ["Ethics Circle", "V1.0", "#A3E635", 3],
];
const MSG = [
  ["u", "Does AI make learning shallower?"],
  [
    "a",
    "Good question. Before I answer: what do you mean by “shallower”? Remembering less, or thinking less deeply?",
  ],
  ["u", "Thinking less deeply, because I don't reason by myself."],
  [
    "a",
    "Then let's test that. Can you think of one case where a tool made you think <b>harder</b>?",
  ],
];
const ERR =
  "Maya couldn't confirm whether this request finished. It won't resend automatically. Check its status or retry this same request to recover.";
// --- scheme tokens ---
const S = {
  A: { name: "A · Banner Desk", banner: true },
  B: { name: "B · Keycap Cabinet", banner: false },
  C: { name: "C · Character Select", banner: false },
};
function header(sc, state, mob) {
  const acts =
    state === "create"
      ? BTN("Back", "back") + BTN("Done", "done", "dis")
      : BTN("New", "plus", "main");
  if (sc === "A")
    return `<div class="relative overflow-hidden rounded-[14px] border-[3px] border-[#111] shadow-[6px_6px_0_#111] ${mob ? "px-4 py-4" : "px-8 py-6"} flex items-center justify-between gap-3" style="${SUN("#FFF1A8")}"><h1 class="font-[Bricolage_Grotesque] font-extrabold ${mob ? "text-3xl" : "text-5xl"}">Chatform</h1><div class="flex gap-3">${acts}</div></div>`;
  if (sc === "B")
    return `<div class="flex items-center justify-between gap-3"><h1 class="font-[Bricolage_Grotesque] font-extrabold ${mob ? "text-3xl" : "text-5xl"} bg-white border-[3px] border-[#111] rounded-[10px] px-4 py-1 shadow-[6px_6px_0_#111] -rotate-1">Chatform</h1><div class="flex gap-3">${acts}</div></div>`;
  return `<div class="flex items-center justify-between gap-3 rounded-[14px] border-[3px] border-[#111] bg-[#111] ${mob ? "px-3 py-3" : "px-6 py-4"} shadow-[6px_6px_0_#FF4D8D]"><h1 class="font-[Bricolage_Grotesque] font-extrabold ${mob ? "text-2xl" : "text-4xl"} text-[#FFE14D]">Chatform</h1><div class="flex gap-3">${acts}</div></div>`;
}
const av = (i, s = 40, bg = "#fff") =>
  `<span class="shrink-0 rounded-[8px] border-[2px] border-[#111] overflow-hidden grid place-items-end" style="width:${s}px;height:${s}px;${SUN(bg)}"><img src="${M[i]}" style="height:${s * 0.9}px"></span>`;
function history(sc, items, mob) {
  const empty = !items.length
    ? `<p class="m-2 rounded-md border-2 border-dashed border-[#111]/40 p-3 text-center text-sm font-bold text-[#4B5563]">No chats yet.</p>`
    : "";
  const row = ([t, d, m, k, cur], i) => {
    const chip = `<span class="rounded-[4px] border-2 border-[#111] px-1.5 text-[10px] font-extrabold ${k === "Team" ? "bg-[#FDBA74]" : "bg-white"}">${k}</span>`;
    const tools = `<span class="ml-auto flex items-center gap-1.5"><small class="text-[10px] font-bold text-[#4B5563]">${d}</small><span aria-label="Pin chat" class="size-7 grid place-items-center rounded-md border-2 border-transparent hover:border-[#111]">${I("pin", 13)}</span><span aria-label="Delete chat" class="size-7 grid place-items-center rounded-full border-2 border-[#111] bg-white shadow-[2px_2px_0_#111]">${I("x", 11)}</span></span>`;
    if (sc === "A")
      return `<div class="flex items-center gap-2 rounded-[10px] border-[3px] border-[#111] px-2 py-2 ${cur ? "bg-[#FF4D8D] shadow-[3px_3px_0_#111]" : "bg-white"}" ${cur ? 'aria-current="page"' : ""}>${av(m, 36, "#F2B79A")}<span class="min-w-0"><span class="block text-[13px] font-extrabold truncate">${t}</span>${chip}</span>${tools}</div>`;
    if (sc === "B")
      return `<div class="flex items-center gap-2 border-b-2 border-dashed border-[#111]/40 px-2 py-2.5 ${cur ? "bg-[#FFE14D]" : ""}"><span class="size-7 grid place-items-center rounded-md border-2 border-[#111] bg-white text-xs font-black shadow-[0_3px_0_#111]" aria-hidden="true">${i + 1}</span>${av(m, 32, "#C9D3F0")}<span class="min-w-0"><span class="block text-[13px] font-extrabold truncate">${t}</span>${chip}</span>${tools}</div>`;
    return `<div class="flex items-center gap-2 rounded-[10px] border-[3px] ${cur ? "border-[#FF4D8D] bg-white shadow-[0_0_0_3px_#111]" : "border-[#111] bg-white"} px-2 py-1.5">${av(m, 44, ["#F2B79A", "#C9D3F0", "#FDBA74", "#C9D9A0"][m])}<span class="min-w-0"><span class="block text-[13px] font-extrabold truncate">${t}</span>${chip}</span>${tools}</div>`;
  };
  const head =
    sc === "B"
      ? `<h2 class="font-[Bricolage_Grotesque] text-xl font-extrabold px-3 py-2 border-b-[3px] border-[#111] bg-[radial-gradient(#111_1px,transparent_1.4px)] bg-[size:8px_8px]"><span class="bg-white px-1">History</span></h2>`
      : sc === "A"
        ? `<h2 class="inline-block -rotate-2 bg-[#FFE14D] border-[2.5px] border-[#111] px-3 py-0.5 font-[Bricolage_Grotesque] text-lg font-extrabold shadow-[2px_2px_0_#111] ml-2 -mt-5">History</h2>`
        : `<h2 class="font-[Bricolage_Grotesque] text-lg font-extrabold px-2 pt-1 text-[#111]">History</h2>`;
  const wrap = sc === "C" ? "bg-[#FDBA74]" : "bg-white";
  return `<aside aria-label="History" class="${mob ? "w-full" : "w-[290px]"} shrink-0 rounded-[12px] border-[3px] border-[#111] ${wrap} shadow-[6px_6px_0_#111] ${sc === "B" ? "" : "p-2"} flex flex-col gap-2">${head}${empty}<div class="flex flex-col ${sc === "B" ? "" : "gap-2"}">${items.map(row).join("")}</div></aside>`;
}
function bubble(sc, [who, t]) {
  if (who === "u")
    return `<div class="flex justify-end"><div class="max-w-[78%] rounded-[10px] border-2 border-[#111] ${sc === "C" ? "bg-[#FFE14D]" : "bg-[#FFE4EE]"} px-3 py-2 text-sm">${t}</div></div>`;
  return `<div class="flex gap-2 items-start">${sc === "B" ? "" : av(0, 30, "#F2B79A")}<div class="max-w-[82%] rounded-[10px] border-2 border-[#111] bg-white px-3 py-2 text-sm leading-relaxed">${t}</div></div>`;
}
function composer(sc, text = "") {
  return `<form class="mt-auto rounded-[10px] border-[3px] border-[#111] bg-white p-2 focus-within:shadow-[3px_3px_0_#FF4D8D]"><textarea aria-label="Message" placeholder="Message" class="w-full resize-none bg-transparent text-sm outline-none px-1" rows="2">${text}</textarea><div class="flex items-center justify-between"><button type="button" aria-label="Attach a file" title="Attach a chat log to this chat only. Only you can see it. .txt, .md, .json, .csv or .html, up to 2 MB." class="size-8 grid place-items-center rounded-md border-2 border-[#111] bg-white shadow-[0_3px_0_#111]">${I("plus", 14)}</button><input type="file" hidden data-testid="chat-attachment-input"><button aria-label="Send" class="size-10 grid place-items-center rounded-[10px] border-[3px] border-[#111] bg-[#FF4D8D] shadow-[0_6px_0_#111] hover:-translate-y-[2px] active:translate-y-[6px] active:shadow-none">${I("up", 18)}</button></div></form>`;
}
function convo(sc, state, mob) {
  const blank = state === "list-blank" || state === "empty";
  const base = `flex-1 min-w-0 rounded-[12px] border-[2px] border-[#111] bg-white shadow-[6px_6px_0_#111] flex flex-col ${mob ? "min-h-[460px]" : "min-h-[620px]"}`;
  if (blank) {
    const art =
      sc === "A"
        ? `<div class="mx-auto w-40 h-32 rounded-[10px] border-[3px] border-dashed border-[#111]/50 grid place-items-end" style="${SUN("#FFF7CC")}"><img src="${M[0]}" class="h-28 opacity-90"></div>`
        : sc === "B"
          ? `<div class="mx-auto flex gap-2" aria-hidden="true">${[1, 2, 3].map((n) => `<span class="size-12 grid place-items-center rounded-[10px] border-[3px] border-[#111] bg-white text-xl font-black shadow-[0_6px_0_#111]">${n}</span>`).join("")}</div>`
          : `<div class="mx-auto flex gap-3" aria-hidden="true">${[0, 1, 2].map((i) => `<span class="w-16 h-20 rounded-[8px] border-[3px] border-dashed border-[#111]/50 grid place-items-end overflow-hidden"><img src="${M[i]}" class="h-16 grayscale opacity-40"></span>`).join("")}</div>`;
    return `<section class="${base} items-center justify-center gap-5 p-8 text-center">${art}<p class="text-sm font-bold text-[#4B5563] max-w-[300px]">Choose a chat from History, or press New to start one.</p></section>`;
  }
  const newc = state === "newconv";
  const title = newc ? "Socrates" : "AI and learning";
  const hd =
    sc === "A"
      ? `<header class="flex items-center gap-3 border-b-2 border-[#111] px-4 py-3">${av(0, 40, "#F2B79A")}<h2 class="inline-block -rotate-1 bg-[#FFE14D] border-[2.5px] border-[#111] px-3 font-[Bricolage_Grotesque] text-lg font-extrabold shadow-[2px_2px_0_#111]">${title}</h2><span class="rounded-[4px] border-2 border-[#111] bg-white px-1.5 text-[11px] font-extrabold shadow-[2px_2px_0_#111]">Agent</span></header>`
      : sc === "B"
        ? `<header class="flex items-center gap-3 border-b-2 border-[#111] px-4 py-3 bg-[radial-gradient(#11111122_1px,transparent_1.4px)] bg-[size:8px_8px]"><h2 class="font-[Bricolage_Grotesque] text-xl font-extrabold bg-white border-2 border-[#111] rounded-md px-2 shadow-[0_4px_0_#111]">${title}</h2><span class="rounded-full border-2 border-[#111] bg-white px-2 text-[11px] font-extrabold">Agent</span></header>`
        : `<header class="flex items-end gap-3 border-b-2 border-[#111] px-4 pt-3 bg-[#111]"><span class="w-16 h-16 rounded-t-[8px] border-[3px] border-b-0 border-[#FFE14D] overflow-hidden grid place-items-end" style="${SUN("#F2B79A")}"><img src="${M[0]}" class="h-14"></span><h2 class="mb-2 font-[Bricolage_Grotesque] text-xl font-extrabold text-[#FFE14D]">${title}</h2><span class="mb-2.5 rounded-[4px] border-2 border-[#FFE14D] px-1.5 text-[11px] font-extrabold text-[#FFE14D]">Agent</span></header>`;
  const log = newc
    ? sc === "A"
      ? `<div class="m-auto w-44 h-36 rounded-[12px] border-[3px] border-[#111] grid place-items-end shadow-[4px_4px_0_#111]" style="${SUN("#F2B79A")}" aria-hidden="true"><img src="${M[0]}" class="h-32"></div>`
      : sc === "B"
        ? `<div class="m-auto flex gap-2" aria-hidden="true">${[0, 1, 2].map(() => `<span class="w-10 h-3 rounded-full border-2 border-dashed border-[#111]/40"></span>`).join("")}</div>`
        : `<div class="m-auto relative" aria-hidden="true"><div class="w-48 h-48 rounded-full border-[3px] border-[#111]" style="${SUN("#FFE14D")}"></div><img src="${M[0]}" class="absolute left-1/2 -translate-x-1/2 bottom-2 h-40"></div>`
    : MSG.map((m) => bubble(sc, m)).join("");
  const err = state === "error";
  return `<section class="${base}">${hd}<div role="log" aria-live="polite" class="flex-1 flex flex-col gap-3 p-4">${log}</div><div class="p-3">${composer(sc, err ? "Why?" : "")}</div></section>`;
}
function tray(sc, mob, fold) {
  // U3 Icon by Kind: chat-bubble sticker beside mascot; collapses after 6s to red "!" badge.
  if (fold)
    return `<div class="${mob ? "mt-4 flex justify-end" : "fixed right-6 bottom-6"}"><span class="relative inline-block"><img src="${M[0]}" class="h-16"><button type="button" class="absolute -top-1 -right-1 size-6 rounded-full bg-[#EF4444] border-2 border-[#111] grid place-items-center text-white text-xs font-black" aria-label="Show notice">!</button></span><div role="status" class="sr-only">${ERR}</div></div>`;
  return `<div class="${mob ? "mt-4" : "fixed right-6 bottom-6"} flex items-end gap-2"><div role="alert" class="relative max-w-[300px] rounded-[10px] border-[3px] border-[#111] bg-[#FFE4E4] p-3 pr-9 shadow-[6px_6px_0_#111] text-[13px] font-medium"><span class="absolute -left-3 -top-3 size-7 rounded-[4px] border-2 border-[#111] bg-[#EF4444] text-white grid place-items-center shadow-[2px_2px_0_#111] -rotate-6" aria-hidden="true">${I("chat", 14)}</span><span aria-label="Dismiss" class="absolute right-2 top-2 size-6 rounded-full border-2 border-[#111] bg-white grid place-items-center">${I("x", 10)}</span>${ERR}<div class="mt-2">${BTN("Check status", "done", "neutral", "!py-1 !text-xs !shadow-[0_3px_0_#111]")}</div></div><img src="${M[0]}" class="h-20"></div>`;
}
function picker(sc, mob) {
  const card = ([n, v, m, bg], i, picked) => {
    if (sc === "A")
      return `<li class="relative bg-white border-[3px] border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] pt-7 px-2.5 pb-2.5 ${picked ? "outline-[4px] outline-[#FF4D8D] outline-offset-2" : ""}" style="transform:rotate(${i % 2 ? 1.2 : -1.2}deg)" aria-pressed="${picked}"><span class="absolute -top-2 -left-2 -rotate-3 bg-white border-2 border-[#111] rounded-[5px] px-1.5 text-[11px] font-extrabold shadow-[2px_2px_0_#111]">${v}</span><span class="absolute -top-3 left-9 right-3 -rotate-2 bg-[#FFE14D] border-[2.5px] border-[#111] text-center text-sm font-extrabold shadow-[2px_2px_0_#111]">${n}</span><div class="h-28 border-[3px] border-[#111] grid place-items-end overflow-hidden" style="${SUN(bg)}"><img src="${M[m]}" class="h-24"></div>${picked ? `<span class="absolute -top-3 -right-3 size-8 rounded-full bg-[#FF4D8D] border-[3px] border-[#111] grid place-items-center" aria-hidden="true">${I("done", 14)}</span>` : ""}</li>`;
    if (sc === "B")
      return `<li class="relative bg-white border-[3px] border-[#111] rounded-[12px] p-2 ${picked ? "bg-[#FFE14D] translate-y-[4px] shadow-[0_2px_0_#111]" : "shadow-[0_6px_0_#111]"}" aria-pressed="${picked}"><div class="h-24 rounded-md border-2 border-[#111] grid place-items-end overflow-hidden bg-[radial-gradient(#11111133_1px,transparent_1.4px)] bg-[size:7px_7px]" style="background-color:${bg}"><img src="${M[m]}" class="h-20"></div><div class="mt-2 flex items-center justify-between"><span class="text-sm font-extrabold">${n}</span><span class="rounded-full border-2 border-[#111] bg-white px-1.5 text-[10px] font-extrabold">${v}</span></div></li>`;
    return `<li class="relative rounded-[10px] border-[3px] ${picked ? "border-[#FF4D8D] shadow-[0_0_0_3px_#111,6px_6px_0_3px_#111]" : "border-[#111] shadow-[6px_6px_0_#111]"} bg-[#111] p-1.5" aria-pressed="${picked}"><div class="h-28 rounded-md grid place-items-end overflow-hidden" style="${SUN(bg)}"><img src="${M[m]}" class="h-24"></div><div class="mt-1.5 flex items-center justify-between px-1"><span class="text-sm font-extrabold text-[#FFE14D]">${n}</span><span class="text-[10px] font-extrabold text-white border border-white rounded px-1">${v}</span></div>${picked ? `<span class="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#FF4D8D] border-2 border-[#111] rounded px-1.5 text-[10px] font-black" aria-hidden="true">P1</span>` : ""}</li>`;
  };
  const team = ([n, v, bg, k], i) => {
    const faces = Array.from(
      { length: k },
      (_, j) =>
        `<span class="-ml-3 first:ml-0 size-11 rounded-full border-[2.5px] border-[#111] bg-white overflow-hidden grid place-items-end"><img src="${M[j % 4]}" class="h-10"></span>`,
    ).join("");
    return `<li class="relative bg-white border-[3px] border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] pt-7 px-2.5 pb-2.5" style="transform:rotate(${i % 2 ? 1.2 : -1.2}deg)"><span class="absolute -top-2 -left-2 bg-white border-2 border-[#111] rounded-[5px] px-1.5 text-[11px] font-extrabold">${v}</span><span class="absolute -top-3 left-9 right-3 -rotate-2 bg-[#FFE14D] border-[2.5px] border-[#111] text-center text-sm font-extrabold shadow-[2px_2px_0_#111]">${n}</span><div class="h-28 border-[3px] border-[#111] flex items-center justify-center" style="background:${bg}">${faces}</div></li>`;
  };
  const col = (title, inner) =>
    `<section class="flex-1 ${sc === "C" ? "bg-[#FDBA74]" : "bg-white"} border-[3px] border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] p-4"><h2 class="inline-block -rotate-1 ${sc === "A" ? "bg-[#A3E635]" : "bg-white"} border-[2.5px] border-[#111] px-3 font-[Bricolage_Grotesque] text-xl font-extrabold shadow-[2px_2px_0_#111] mb-5">${title}</h2>${inner}</section>`;
  const g = `grid ${mob ? "grid-cols-2" : "grid-cols-3"} gap-x-5 gap-y-8 list-none p-0 m-0`;
  return `<div class="flex ${mob ? "flex-col" : ""} gap-6">${col("Agents", `<ul class="${g}">${AG.map((a, i) => card(a, i, i === 0)).join("")}</ul>`)}${col("Teams", `<ul class="${g}">${TM.map(team).join("")}</ul><p class="hidden">No Teams yet.</p>`)}</div>`;
}
function body(sc, state, mob) {
  const h = header(sc, state === "list-blank" && false ? "" : state, mob);
  if (state === "create")
    return h + `<div class="mt-8">${picker(sc, mob)}</div>`;
  const items =
    state === "empty"
      ? []
      : state === "newconv"
        ? [
            ["Socrates", "10/27/2026", 0, "Agent", 1],
            ...HIST.slice(0, 1).map((x) => [...x.slice(0, 4), 0]),
          ]
        : HIST;
  const st = state === "empty" ? "empty" : state;
  const main = `<div class="mt-8 flex ${mob ? "flex-col" : ""} gap-6">${history(sc, items, mob)}${convo(sc, st, mob)}</div>`;
  return (
    h +
    main +
    (state === "error"
      ? tray(sc, mob, false)
      : state === "errfold"
        ? tray(sc, mob, true)
        : "")
  );
}
const RS = R + "src/real-shell/";
const SB = fs.readFileSync(RS + "sidebar-1440.html", "utf8"),
  MT = fs.readFileSync(RS + "mtop-390.html", "utf8"),
  FF = "<style>" + fs.readFileSync(RS + "fonts.css", "utf8") + "</style>";
const DRAWER = SB.replace(/^<header /, "<header data-drawer-closed hidden ");
function page(sc, state, w) {
  const mob = w < 500;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">${FONT}${FF}<script>${TW}</script></head><body class="m-0 font-[Lexend] text-[#111]"><div class="flex ${mob ? "flex-col" : ""} min-h-screen ${GRID}">${mob ? MT + DRAWER : MT.replace(/^<(\w+) /, "<$1 hidden ") + SB}<main class="flex-1 min-w-0 ${mob ? "px-4 py-5" : "px-14 py-10"} ${mob ? "" : "max-w-[1200px]"}">${body(sc, state, mob)}</main></div></body></html>`;
}
const br = await chromium.launch();
const states = process.argv[2]
  ? process.argv[2].split(",")
  : ["list", "create", "empty", "newconv", "error", "errfold"];
for (const sc of ["A", "B", "C"]) {
  fs.mkdirSync(`${R}scheme-${sc}`, { recursive: true });
  for (const st of states)
    for (const w of [1440, 390]) {
      const p = await br.newPage({
        viewport: { width: w, height: w > 500 ? 900 : 844 },
      });
      const html = page(sc, st === "list" ? "list" : st, w);
      fs.writeFileSync(
        `${R}scheme-${sc}/${st}-${w}-rs.html`,
        html
          .replace(TW, "/* tailwind browser build inlined at render */")
          .replace(
            FF,
            '<link rel="stylesheet" href="../src/real-shell/fonts.css">',
          ),
      );
      await p.setContent(html, { waitUntil: "networkidle" });
      await p.waitForTimeout(400);
      await p.screenshot({
        path: `${R}scheme-${sc}/${st}-${w}-rs.png`,
        fullPage: true,
      });
      fs.mkdirSync(R + "audit", { recursive: true });
      fs.writeFileSync(
        `${R}audit/${sc}-${st}-${w}.json`,
        JSON.stringify(
          await p.evaluate(() => {
            const vis = (e) => {
              const r = e.getBoundingClientRect(),
                s = getComputedStyle(e);
              return (
                r.width > 0 &&
                r.height > 0 &&
                s.visibility !== "hidden" &&
                s.display !== "none"
              );
            };
            const hiddenTexts = [
              ...document.querySelectorAll("[hidden],.hidden"),
            ]
              .map((e) => e.textContent.trim())
              .filter(Boolean);
            const texts = [];
            const tw = document.createTreeWalker(
              document.body,
              NodeFilter.SHOW_TEXT,
            );
            let n;
            while ((n = tw.nextNode())) {
              const t = n.textContent.trim();
              if (
                t &&
                n.parentElement &&
                vis(n.parentElement) &&
                !n.parentElement.closest("script,style,[aria-hidden=true]")
              )
                texts.push(t);
            }
            const attrs = [
              ...document.querySelectorAll(
                "[aria-label],[title],[alt],[placeholder],[data-testid]",
              ),
            ].map((e) => ({
              aria: e.getAttribute("aria-label"),
              title: e.getAttribute("title"),
              alt: e.getAttribute("alt"),
              ph: e.getAttribute("placeholder"),
              testid: e.getAttribute("data-testid"),
            }));
            return { texts, attrs, hiddenTexts };
          }),
        ),
      );
      await p.close();
    }
}
await br.close();
