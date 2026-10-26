import { chromium } from "playwright";
import fs from "fs";
const OUT = "/workspace/maya-ui/proposals/chatform/src/real-shell";
fs.mkdirSync(OUT, { recursive: true });
const M = JSON.parse(fs.readFileSync("./mocks.json"));
const user = {
  id: "u2",
  username: "s01",
  display_name: "李同学",
  avatar: null,
  courses: [
    { course_id: "11111111-1111-4111-8111-111111111111", role: "student" },
  ],
  groups: [
    {
      group_id: "22222222-2222-4222-8222-222222222222",
      course_id: "11111111-1111-4111-8111-111111111111",
      name: "第一组",
      role: "member",
    },
  ],
};
const b = await chromium.launch();
for (const [w, h] of [
  [1440, 900],
  [390, 844],
]) {
  const page = await b.newPage({ viewport: { width: w, height: h } });
  await page.route("**/api/v1/**", (r) => {
    const p = new URL(r.request().url()).pathname.replace(/^\/api\/v1/, "");
    const m = r.request().method();
    if (p === "/auth/me")
      return r.fulfill({
        json: { user, csrf_token: "x", expires_at: "2030-01-01T00:00:00Z" },
      });
    for (const [re, body] of Object.entries(M)) {
      const [mm, pat] = re.includes(" ") ? re.split(" ") : ["GET", re];
      if (mm === m && new RegExp("^" + pat + "$").test(p))
        return r.fulfill({ json: body });
    }
    r.fulfill({ json: [] });
  });
  await page.goto("http://localhost:3311/student/chat", {
    waitUntil: "networkidle",
  });
  await page.waitForTimeout(2500);
  const res = await page.evaluate(async (mob) => {
    const hdr = document.querySelector("header[id]");
    const root = mob
      ? [...hdr.parentElement.children].find(
          (e) =>
            e !== hdr &&
            e.getBoundingClientRect().top < 5 &&
            e.getBoundingClientRect().height > 30 &&
            e.getBoundingClientRect().height < 120,
        )
      : hdr;
    // hide New workspace action (moves to chat page header per proposal)
    const news = [...root.querySelectorAll("button,a")].filter(
      (e) => e.textContent.trim() === "New",
    );
    const clone = root.cloneNode(true);
    const S = [root, ...root.querySelectorAll("*")],
      C = [clone, ...clone.querySelectorAll("*")];
    const fams = new Set();
    S.forEach((e, i) => {
      const cs = getComputedStyle(e);
      let t = "";
      for (const p of cs) {
        if (
          p.startsWith("--") ||
          p.startsWith("transition") ||
          p.startsWith("animation")
        )
          continue;
        t += p + ":" + cs.getPropertyValue(p) + ";";
      }
      C[i].setAttribute("style", t);
      C[i].removeAttribute("class");
      fams.add(cs.fontFamily);
      if (news.includes(e)) C[i].setAttribute("data-removed-new", "");
    });
    C.forEach((e) => {
      if (e.hasAttribute("data-removed-new")) e.remove();
    });
    clone.style.position = "sticky";
    clone.style.top = "0";
    clone.style.visibility = "visible";
    clone.style.transform = "none";
    // font faces
    const faces = [];
    for (const ss of document.styleSheets) {
      let rs;
      try {
        rs = ss.cssRules;
      } catch {
        continue;
      }
      for (const r of rs) {
        if (r instanceof CSSFontFaceRule) {
          const fam = r.style
            .getPropertyValue("font-family")
            .replace(/['"]/g, "");
          if ([...fams].some((f) => f.includes(fam))) {
            let css = r.cssText;
            const urls = [...css.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map(
              (m) => m[1],
            );
            for (const u of urls) {
              const ab = await (
                await fetch(new URL(u, ss.href || location.href))
              ).arrayBuffer();
              let s = "";
              const by = new Uint8Array(ab);
              for (let k = 0; k < by.length; k++)
                s += String.fromCharCode(by[k]);
              css = css.replace(u, "data:font/woff2;base64," + btoa(s));
            }
            faces.push(css);
          }
        }
      }
    }
    return {
      html: clone.outerHTML,
      faces: faces.join("\n"),
      removed: news.length,
      w: root.getBoundingClientRect().width,
      h: root.getBoundingClientRect().height,
    };
  }, w === 390);
  fs.writeFileSync(
    `${OUT}/${w === 390 ? "mtop-390" : "sidebar-1440"}.html`,
    res.html,
  );
  fs.writeFileSync(`${OUT}/fonts-${w}.css`, res.faces);
  console.log(w, res.removed, res.w, res.h, res.html.length, res.faces.length);
  await page.close();
}
await b.close();
