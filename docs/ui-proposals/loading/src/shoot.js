const { chromium } = require("playwright");
const OUT = process.argv[2],
  only = process.argv[3];
const C = "00000000-0000-4000-8000-0000000000c1",
  G = "00000000-0000-4000-8000-0000000000a1";
const session = {
  csrf_token: "x",
  expires_at: "2099-01-01T00:00:00Z",
  user: {
    id: "u1",
    username: "li",
    display_name: "李同学",
    courses: [{ course_id: C, role: "student" }],
    groups: [{ group_id: G, course_id: C, name: "第一组", id: G }],
  },
};
(async () => {
  const b = await chromium.launch();
  for (const s of ["A", "B", "C"])
    for (const room of ["page", "content", "inline"])
      for (const w of [1440, 390]) {
        if (only && !`${s}-${room}-${w}`.startsWith(only)) continue;
        if (room === "inline" && w === 390) continue;
        const p = await b.newPage({
          viewport: { width: w, height: w > 500 ? 900 : 844 },
        });
        await p.route("**/api/v1/**", (r) => {
          const path = new URL(r.request().url()).pathname.replace(
            "/api/v1",
            "",
          );
          if (path === "/auth/me")
            return r.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify(session),
            });
          if (/^\/groups\/[^/]+$/.test(path))
            return r.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify({
                id: G,
                course_id: C,
                name: "g",
                members: [],
              }),
            });
          r.fulfill({
            status: 200,
            contentType: "application/json",
            body: "[]",
          });
        });
        await p.goto(
          `http://127.0.0.1:3100/loading-proposals?s=${s}&room=${room}`,
          { waitUntil: "networkidle", timeout: 120000 },
        );
        await p.addStyleTag({
          content: "nextjs-portal{display:none!important}",
        });
        await p.waitForTimeout(1500);
        await p.screenshot({ path: `${OUT}/${s}-${room}-${w}.png` });
        if (room === "page" && w === 1440)
          for (const f of [1, 2]) {
            await p.waitForTimeout(450);
            await p.screenshot({ path: `${OUT}/${s}-${room}-${w}-f${f}.png` });
          }
        await p.close();
      }
  await b.close();
})();
