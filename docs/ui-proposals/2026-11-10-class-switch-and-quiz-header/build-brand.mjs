import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const svg = (body) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;
const stroke =
  'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"';
const icon = {
  check: svg(`<path d="M5 12.5 10 17.5 19 7" ${stroke}/>`),
  chevron: svg(`<path d="m6 9 6 6 6-6" ${stroke}/>`),
  menu: svg(`<path d="M4 7h16M4 12h16M4 17h16" ${stroke}/>`),
  left: svg(`<path d="M14 6 8 12l6 6" ${stroke}/>`),
  agent: svg(
    `<circle cx="12" cy="8" r="3" ${stroke}/><path d="M6 19c1.2-3 3.2-4.5 6-4.5S16.8 16 18 19" ${stroke}/>`,
  ),
  team: svg(
    `<circle cx="8" cy="9" r="2.2" ${stroke}/><circle cx="16" cy="9" r="2.2" ${stroke}/><path d="M4 18c.6-2.4 2-3.5 4-3.5s3.4 1.1 4 3.5M12 18c.6-2.4 2-3.5 4-3.5s3.4 1.1 4 3.5" ${stroke}/>`,
  ),
  file: svg(
    `<path d="M7 3h7l4 4v14H7z" ${stroke}/><path d="M14 3v5h5" ${stroke}/>`,
  ),
  mic: svg(
    `<rect x="9" y="3" width="6" height="11" rx="3" ${stroke}/><path d="M6 11a6 6 0 0 0 12 0M12 17v4" ${stroke}/>`,
  ),
  book: svg(
    `<path d="M5 5h6a3 3 0 0 1 3 3v12H8a3 3 0 0 0-3 3zM19 5h-6a3 3 0 0 0-3 3v12h6a3 3 0 0 1 3 3z" ${stroke}/>`,
  ),
  chat: svg(`<path d="M5 6h14v9H8l-3 3z" ${stroke}/>`),
  live: svg(
    `<circle cx="12" cy="12" r="3" ${stroke}/><path d="M7 7a7 7 0 0 0 0 10M17 7a7 7 0 0 1 0 10" ${stroke}/>`,
  ),
  quiz: svg(`<path d="M7 4h10v16H7zM9 8h6M9 12h6" ${stroke}/>`),
  people: svg(
    `<circle cx="9" cy="8" r="2.4" ${stroke}/><circle cx="16" cy="9" r="2" ${stroke}/><path d="M4 18c.7-2.6 2.3-4 5-4s4.3 1.4 5 4M14 14.2c1.6-.2 3 .6 4 2.8" ${stroke}/>`,
  ),
};

const dot = `<span class="dot" aria-hidden="true"></span>`;
const longName = "Mayaform-North-Campus-Cultural-Exchange";

function menu(id) {
  return `<p class="menu-cap kicker" id="${id}-label">Classes</p>
<div class="class-menu" id="${id}" role="menu" aria-labelledby="${id}-label">
  <button type="button" role="menuitemradio" aria-checked="true">${icon.check}<span class="label-clip">Mayaform-1001</span><span class="sr">Current</span></button>
  <button type="button" role="menuitemradio" aria-checked="false"><span class="mark" aria-hidden="true"></span><span class="label-clip">Mayaform-1002</span></button>
  <button type="button" role="menuitemradio" aria-checked="false" title="${longName}"><span class="mark" aria-hidden="true"></span><span class="label-clip">${longName}</span></button>
</div>`;
}

function item(label, glyph) {
  return `<li><button type="button" class="item">${glyph}<span>${label}</span></button></li>`;
}

const nav = `<nav class="nav" aria-label="Teacher navigation">
  <div class="group study"><h2><i class="swatch study" aria-hidden="true"></i>Studyform</h2>
    <ul>${item("Agents", icon.agent)}${item("Teams", icon.team)}</ul></div>
  <div class="group brain"><h2><i class="swatch brain" aria-hidden="true"></i>Brainform</h2>
    <ul>${item("RAG", icon.file)}${item("Voices", icon.mic)}${item("Knowledge", icon.book)}</ul></div>
  <div class="group chat"><h2><i class="swatch chat" aria-hidden="true"></i>Chatform</h2>
    <ul>${item("Chat with Agent", icon.chat)}${item("Chat with Team", icon.team)}</ul></div>
  <div class="group room"><h2><i class="swatch room" aria-hidden="true"></i>Classroom</h2>
    <ul>${item("Debates", icon.live)}${item("Accounts", icon.people)}${item("Quizzes", icon.quiz)}</ul></div>
</nav>`;

const hero = `<div class="frame"><section class="hero" aria-labelledby="welcome-title">
  <div class="hero-copy">
    <h1 id="welcome-title">Welcome <span class="name">Maya</span></h1>
    <div class="stats">
      <div class="stat lime"><b>17</b><span>Groups</span></div>
      <div class="stat cyan"><b>50</b><span>Students</span></div>
    </div>
  </div>
  <div class="hero-art">
    <span class="chip" aria-hidden="true">Holdem</span>
    <svg class="scholars" viewBox="0 0 300 176" aria-hidden="true">
      <rect x="18" y="78" width="52" height="78" rx="16" fill="#67E8F9" stroke="#111" stroke-width="3"/>
      <circle cx="44" cy="62" r="20" fill="#FFF7CC" stroke="#111" stroke-width="3"/>
      <rect x="86" y="64" width="48" height="92" rx="18" fill="#FF4D8D" stroke="#111" stroke-width="3"/>
      <circle cx="110" cy="48" r="22" fill="#fff" stroke="#111" stroke-width="3"/>
      <path d="M168 86c8-28 40-28 48 0v70h-48z" fill="#A3E635" stroke="#111" stroke-width="3"/>
      <circle cx="192" cy="62" r="20" fill="#FDBA74" stroke="#111" stroke-width="3"/>
      <rect x="230" y="88" width="50" height="68" rx="14" fill="#C4B5FD" stroke="#111" stroke-width="3"/>
      <circle cx="255" cy="70" r="20" fill="#FFF7CC" stroke="#111" stroke-width="3"/>
    </svg>
  </div>
</section></div>`;

const script = `<script>
  if (new URLSearchParams(location.search).has("collapsed")) {
    document.documentElement.classList.add("collapsed");
  }
  document.querySelectorAll("[aria-haspopup='menu']").forEach((button) => {
    const menu = document.getElementById(button.getAttribute("aria-controls"));
    if (!menu) return;
    const items = () => [...menu.querySelectorAll("[role='menuitemradio']")];
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowDown" && event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      button.setAttribute("aria-expanded", "true");
      menu.hidden = false;
      items()[0]?.focus();
    });
    menu.addEventListener("keydown", (event) => {
      const list = items();
      const index = list.indexOf(document.activeElement);
      if (event.key === "Escape") {
        event.preventDefault();
        button.setAttribute("aria-expanded", "false");
        menu.hidden = true;
        button.focus();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        list[Math.min(list.length - 1, index + 1)]?.focus();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        list[Math.max(0, index - 1)]?.focus();
      } else if (event.key === "Home") {
        event.preventDefault();
        list[0]?.focus();
      } else if (event.key === "End") {
        event.preventDefault();
        list[list.length - 1]?.focus();
      }
    });
  });
</script>`;

function page({
  file,
  title,
  caption,
  bodyClass,
  topbar,
  expanded,
  collapsed,
}) {
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${title}</title>
    <link rel="stylesheet" href="fonts/fonts.css" />
    <link rel="stylesheet" href="mock.css" />
  </head>
  <body class="home round2 ${bodyClass}">
    <p class="example"><b>EXAMPLE DATA</b> <span class="detail">${caption}</span></p>
    <div class="app">
      <header class="topbar">
        <button type="button" class="top-menu" aria-label="Open menu">${icon.menu}</button>
        ${topbar}
      </header>
      <div class="mobile-menu">${menu("class-menu-mobile")}</div>
      <aside class="sidebar">
        <button type="button" class="collapse" aria-label="Collapse sidebar">${icon.left}</button>
        <div class="side-scroll">
          <div class="brand-expanded">${expanded}</div>
          <div class="brand-collapsed">${collapsed}</div>
          ${nav}
        </div>
        <div class="flyout">${menu("class-menu-flyout")}</div>
        <div class="side-foot">
          <p class="help"><b>Meet Problems?</b><span>Send to t330034059@mail.bnbu.edu.cn</span></p>
          <button type="button" class="logout">Logout</button>
        </div>
      </aside>
      <main>${hero}</main>
    </div>
    ${script}
  </body>
</html>
`;
  writeFileSync(join(root, file), html);
}

const splitHome = `<a class="split-home" href="#welcome-title" aria-current="page">
  ${dot}
  <span class="split-text"><span class="word label-clip">Mayaform-</span><span class="suffix label-clip">1001</span></span>
</a>`;
const splitGo = (id) =>
  `<button type="button" class="split-go" aria-label="Switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="${id}">${icon.chevron}</button>`;

page({
  file: "brand-split.html",
  title: "Scheme B1 · split brand button",
  caption:
    "Scheme B1 · sample classes Maya1001 and Maya1002. The long row shows truncation. Not the product.",
  bodyClass: "",
  topbar: `<div class="split">${splitHome}${splitGo("class-menu-mobile")}</div>`,
  expanded: `<div class="split">${splitHome}${splitGo("class-menu-desk")}</div>${menu("class-menu-desk")}`,
  collapsed: `<a class="rail-btn" href="#welcome-title" aria-current="page" aria-label="Mayaform-1001, home">${dot}</a>
    <button type="button" class="rail-btn" aria-label="Switch class, current class 1001" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-flyout">${icon.chevron}<small>1001</small></button>`,
});

page({
  file: "brand-chip.html",
  title: "Scheme B2 · class chip on the brand capsule",
  caption:
    "Scheme B2 · sample classes Maya1001 and Maya1002. The long row shows truncation. Not the product.",
  bodyClass: "",
  topbar: `<div class="capsule">
      <a class="capsule-home" href="#welcome-title" aria-current="page">${dot}<span class="label-clip">Mayaform</span></a>
      <button type="button" class="capsule-chip" aria-label="Current class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-mobile"><span class="label-clip">1001</span>${icon.chevron}</button>
    </div>`,
  expanded: `<div class="capsule">
      <a class="capsule-home" href="#welcome-title" aria-current="page">${dot}<span class="label-clip">Mayaform</span></a>
      <button type="button" class="capsule-chip" aria-label="Current class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-desk"><span class="label-clip">1001</span>${icon.chevron}</button>
    </div>${menu("class-menu-desk")}`,
  collapsed: `<a class="rail-btn" href="#welcome-title" aria-current="page" aria-label="Mayaform, home">${dot}</a>
    <button type="button" class="rail-btn chip" aria-label="Current class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-flyout">${icon.check}<small>1001</small></button>`,
});

page({
  file: "brand-subline.html",
  title: "Scheme B3 · class line under the brand",
  caption:
    "Scheme B3 · sample classes Maya1001 and Maya1002. The long row shows truncation. Not the product.",
  bodyClass: "sub",
  topbar: `<a class="brand-home" href="#welcome-title" aria-current="page">${dot}<span>Mayaform</span></a>
    <button type="button" class="classline" aria-label="Class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-mobile"><span class="kicker">Class</span>${icon.check}<span class="label-clip">1001</span>${icon.chevron}</button>`,
  expanded: `<a class="brand-home" href="#welcome-title" aria-current="page">${dot}<span>Mayaform</span></a>
    <button type="button" class="classline" aria-label="Class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-desk"><span class="kicker">Class</span>${icon.check}<span class="label-clip">1001</span>${icon.chevron}</button>
    ${menu("class-menu-desk")}`,
  collapsed: `<a class="rail-btn" href="#welcome-title" aria-current="page" aria-label="Mayaform, home">${dot}</a>
    <button type="button" class="rail-btn" aria-label="Class 1001, switch class" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu-flyout"><small>Class</small><small>1001</small></button>`,
});

console.log("wrote three brand mocks");
