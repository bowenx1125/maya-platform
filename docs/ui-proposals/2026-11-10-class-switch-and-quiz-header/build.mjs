import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));

const svg = (paths) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
const stroke =
  'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"';

const icon = {
  check: svg(`<path d="M5 12.5 10 17.5 19 7" ${stroke}/>`),
  chevron: svg(`<path d="m6 9 6 6 6-6" ${stroke}/>`),
  menu: svg(`<path d="M4 7h16M4 12h16M4 17h16" ${stroke}/>`),
  pause: svg(`<path d="M8 5v14M16 5v14" ${stroke}/>`),
  download: svg(`<path d="M12 4v11M8 11l4 4 4-4M5 20h14" ${stroke}/>`),
  back: svg(`<path d="M14 6 8 12l6 6M8 12h11" ${stroke}/>`),
  undo: svg(`<path d="M9 14 4 9l5-5M4 9h9a6 6 0 1 1 0 12h-3" ${stroke}/>`),
  done: svg(`<path d="M5 12.5 10 17.5 19 7" ${stroke}/>`),
  lock: svg(
    `<rect x="5" y="11" width="14" height="9" rx="2" ${stroke}/><path d="M8 11V8a4 4 0 0 1 8 0v3" ${stroke}/>`,
  ),
  more: svg(
    `<circle cx="6" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="18" cy="12" r="1.5" fill="currentColor"/>`,
  ),
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

const scholars = `<svg class="scholars" viewBox="0 0 300 176" aria-hidden="true">
  <g>
    <rect x="18" y="78" width="52" height="78" rx="16" fill="#67E8F9" stroke="#111" stroke-width="3"/>
    <circle cx="44" cy="62" r="20" fill="#FFF7CC" stroke="#111" stroke-width="3"/>
    <circle cx="37" cy="62" r="2.2" fill="#111"/><circle cx="51" cy="62" r="2.2" fill="#111"/>
    <path d="M36 72h16" fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round"/>
  </g>
  <g>
    <rect x="86" y="64" width="48" height="92" rx="18" fill="#FF4D8D" stroke="#111" stroke-width="3"/>
    <circle cx="110" cy="48" r="22" fill="#fff" stroke="#111" stroke-width="3"/>
    <circle cx="102" cy="48" r="2.2" fill="#111"/><circle cx="118" cy="48" r="2.2" fill="#111"/>
    <path d="M102 58c4 4 12 4 16 0" fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round"/>
  </g>
  <g>
    <path d="M168 86c8-28 40-28 48 0v70h-48z" fill="#A3E635" stroke="#111" stroke-width="3"/>
    <circle cx="192" cy="62" r="20" fill="#FDBA74" stroke="#111" stroke-width="3"/>
    <circle cx="185" cy="62" r="2.2" fill="#111"/><circle cx="199" cy="62" r="2.2" fill="#111"/>
    <path d="M184 72h16" fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round"/>
  </g>
  <g>
    <rect x="230" y="88" width="50" height="68" rx="14" fill="#C4B5FD" stroke="#111" stroke-width="3"/>
    <circle cx="255" cy="70" r="20" fill="#FFF7CC" stroke="#111" stroke-width="3"/>
    <circle cx="248" cy="70" r="2.2" fill="#111"/><circle cx="262" cy="70" r="2.2" fill="#111"/>
    <path d="M248 80c3 3 11 3 14 0" fill="none" stroke="#111" stroke-width="2.4" stroke-linecap="round"/>
  </g>
</svg>`;

function item(label, glyph, current = false) {
  const pressed = current ? ' aria-current="page"' : "";
  return `<li><button type="button" class="item"${pressed}>${glyph}<span>${label}</span></button></li>`;
}

function sidebar(page) {
  const home = page === "home";
  const quiz = page === "quiz";
  return `<aside class="sidebar">
    <button type="button" class="collapse" aria-label="Collapse sidebar">${icon.left}</button>
    <div class="side-scroll">
      <button type="button" class="brand"${home ? ' aria-current="page"' : ""}>
        <span class="dot" aria-hidden="true"></span><span>Mayaform</span>
      </button>
      ${page === "home" ? "<!--CLASS-->" : ""}
      <nav class="nav" aria-label="Teacher navigation">
        <div class="group study">
          <h2><i class="swatch study" aria-hidden="true"></i>Studyform</h2>
          <ul>
            ${item("Agents", icon.agent)}
            ${item("Teams", icon.team)}
          </ul>
        </div>
        <div class="group brain">
          <h2><i class="swatch brain" aria-hidden="true"></i>Brainform</h2>
          <ul>
            ${item("RAG", icon.file)}
            ${item("Voices", icon.mic)}
            ${item("Knowledge", icon.book)}
          </ul>
        </div>
        <div class="group chat">
          <h2><i class="swatch chat" aria-hidden="true"></i>Chatform</h2>
          <ul>
            ${item("Chat with Agent", icon.chat)}
            ${item("Chat with Team", icon.team)}
          </ul>
        </div>
        <div class="group room">
          <h2><i class="swatch room" aria-hidden="true"></i>Classroom</h2>
          <ul>
            ${item("Debates", icon.live)}
            ${item("Accounts", icon.people)}
            ${item("Quizzes", icon.quiz, quiz)}
          </ul>
        </div>
      </nav>
    </div>
    <div class="side-foot">
      <p class="help"><b>Meet Problems?</b><span>Send to t330034059@mail.bnbu.edu.cn</span></p>
      <button type="button" class="logout">Logout</button>
    </div>
  </aside>`;
}

const seg = `<div class="class-field">
  <span class="kicker" id="class-label">Class</span>
  <div class="seg" role="group" aria-labelledby="class-label">
    <button type="button" aria-pressed="false">Maya1002</button>
    <button type="button" aria-pressed="true">${icon.check}<span>Maya1001</span></button>
  </div>
</div>`;

const sideClass = `<div class="side-class">
  <span class="kicker" id="side-class-label">Class</span>
  <button type="button" class="side-btn" aria-haspopup="menu" aria-expanded="true" aria-controls="class-menu">
    <span>Maya1001</span>${icon.chevron}
  </button>
  <div class="side-menu" id="class-menu" role="menu" aria-labelledby="side-class-label">
    <button type="button" role="menuitemradio" aria-checked="true">${icon.check}<span>Maya1001</span></button>
    <button type="button" role="menuitemradio" aria-checked="false"><span class="mark" aria-hidden="true"></span><span>Maya1002</span></button>
  </div>
</div>`;

function hero(classField) {
  return `<section class="hero" aria-labelledby="welcome-title">
    <div class="hero-copy">
      <h1 id="welcome-title">Welcome <span class="name">Maya</span></h1>
      ${classField}
      <div class="stats">
        <div class="stat lime"><b>17</b><span>Groups</span></div>
        <div class="stat cyan"><b>50</b><span>Students</span></div>
      </div>
    </div>
    <div class="hero-art">
      <span class="chip" aria-hidden="true">Holdem</span>
      ${scholars}
      <p class="sr">Four scholars of the academy, whose eyes follow the cursor and look away while a password is typed.</p>
    </div>
  </section>
  <h2 class="tape">Agents · 2</h2>
  <div class="cards">
    <article class="card"><div class="sun" aria-hidden="true"></div><b>Sample One</b><span>V1.0 · Public</span></article>
    <article class="card"><div class="sun" aria-hidden="true"></div><b>Sample Two</b><span>V1.0 · Private</span></article>
  </div>`;
}

const classBar = `<section class="classbar" aria-labelledby="bar-class">
  <div>
    <span class="kicker" id="bar-class">Class</span>
    <p class="now">Current class <strong>Maya1001</strong></p>
  </div>
  <div class="seg" role="group" aria-labelledby="bar-class">
    <button type="button" aria-pressed="false">Maya1002</button>
    <button type="button" aria-pressed="true">${icon.check}<span>Maya1001</span></button>
  </div>
</section>`;

function key(name, glyph, primary = false) {
  const tone = primary ? " key primary" : " key";
  return `<button type="button" class="${tone.trim()}">${glyph}<span>${name}</span></button>`;
}

const live = `<span class="live"><i aria-hidden="true"></i><span aria-hidden="true">LIVE</span><span class="sr">Accepting submissions</span></span>`;

const title = `<div class="qtitle"><h1>Concluding Questionnaire · 终点问卷</h1>${live}</div>`;

const tabs = `<div class="tabs" role="tablist" aria-label="Quiz">
  <button type="button" role="tab" aria-selected="true">Paper</button>
  <button type="button" role="tab" aria-selected="false">Submissions <span class="count">9</span></button>
</div>`;

function notice(extra = "") {
  return `<div class="notice" role="status">
    <p>${icon.lock}<span>Unpublish this quiz before editing it.</span></p>
    ${key("Unpublish", icon.undo)}
    ${extra}
  </div>`;
}

const question = `<section class="question" aria-labelledby="q1">
  <div class="qmeta">
    <span class="num">#01</span>
    <span class="pill">Multiple choice</span>
    <span class="pts">1 pt</span>
  </div>
  <p class="prompt" id="q1">Which sentence best states the group's conclusion?</p>
  <ul class="choices">
    <li class="correct"><span class="tick">${icon.check}</span>Trade came first<span class="sr"> (answer key)</span></li>
    <li>The ports stayed closed</li>
  </ul>
</section>`;

const more = `<div class="more-menu" id="quiz-more" role="menu" aria-label="More actions">
  <button type="button" role="menuitem">${icon.pause}<span>Pause evaluation</span></button>
  <button type="button" role="menuitem">${icon.download}<span>Download</span></button>
</div>`;

function page({ file, titleText, caption, kind, main, chip = "", side = "" }) {
  const shell = sidebar(kind === "home" ? "home" : "quiz").replace(
    "<!--CLASS-->",
    side,
  );
  const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${titleText}</title>
    <link rel="stylesheet" href="fonts/fonts.css" />
    <link rel="stylesheet" href="mock.css" />
  </head>
  <body class="${kind}">
    <p class="example"><b>EXAMPLE DATA</b> <span class="detail">${caption}</span></p>
    <div class="app">
      <header class="topbar">
        <button type="button" class="top-menu" aria-label="Open menu">${icon.menu}</button>
        <span class="top-brand"><span class="dot" aria-hidden="true"></span>Mayaform</span>
        ${chip}
      </header>
      ${shell}
      <main>${main}</main>
    </div>
  </body>
</html>
`;
  writeFileSync(join(root, file), html);
}

const chip = `<button type="button" class="class-chip" aria-haspopup="menu" aria-expanded="false">
  <span class="sr">Current class</span><span>Maya1001</span>${icon.chevron}
</button>`;

page({
  file: "switcher-a.html",
  titleText: "Scheme A · class segment inside the banner",
  caption:
    "Scheme A · sample teacher Maya, classes Maya1001 and Maya1002, 17 groups, 50 students. Not the product.",
  kind: "home",
  main: `<div class="frame">${hero(seg)}</div>`,
});

page({
  file: "switcher-b.html",
  titleText: "Scheme B · class menu in the sidebar",
  caption:
    "Scheme B · sample teacher Maya, classes Maya1001 and Maya1002. The menu is open. Not the product.",
  kind: "home",
  chip,
  side: sideClass,
  main: `<div class="frame">${hero("")}</div>`,
});

page({
  file: "switcher-c.html",
  titleText: "Scheme C · class bar above the banner",
  caption:
    "Scheme C · sample teacher Maya, classes Maya1001 and Maya1002, 17 groups, 50 students. Not the product.",
  kind: "home",
  main: `<div class="frame">${classBar}${hero("")}</div>`,
});

page({
  file: "quizheader-a.html",
  titleText: "Scheme A · quiz title on its own row",
  caption:
    "Scheme A · sample quiz “Concluding Questionnaire · 终点问卷”, 9 submissions. Not the product.",
  kind: "quiz",
  main: `<div class="frame">
    <header class="qbanner">${title}<div class="qactions">${key("Pause evaluation", icon.pause)}${key("Download", icon.download)}${key("Back", icon.back)}${key("Done", icon.done, true)}</div></header>
    ${tabs}${notice()}${question}
  </div>`,
});

page({
  file: "quizheader-b.html",
  titleText: "Scheme B · breadcrumb and ranked actions",
  caption:
    "Scheme B · sample quiz “Concluding Questionnaire · 终点问卷”, 9 submissions. Not the product.",
  kind: "quiz",
  main: `<div class="frame">
    <button type="button" class="crumb" aria-label="Back to quizzes">${icon.back}<span>Quizzes</span></button>
    <header class="qbanner">${title}<div class="qactions pair">${key("Pause evaluation", icon.pause)}${key("Done", icon.done, true)}</div></header>
    ${tabs}${notice(key("Download", icon.download))}${question}
  </div>`,
});

page({
  file: "quizheader-c.html",
  titleText: "Scheme C · secondary quiz actions in a menu",
  caption:
    "Scheme C · sample quiz “Concluding Questionnaire · 终点问卷”. The More menu is open. Not the product.",
  kind: "quiz",
  main: `<div class="frame">
    <header class="qbanner">${title}
      <div class="qactions trio">${key("Back", icon.back)}${key("Done", icon.done, true)}<button type="button" class="more-btn" aria-label="More actions" aria-haspopup="menu" aria-expanded="true" aria-controls="quiz-more">${icon.more}</button></div>
      ${more}
    </header>
    ${tabs}${notice()}${question}
  </div>`,
});

console.log("wrote six mock pages");
