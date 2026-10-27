const { chromium } = require("playwright");
const OUT = process.argv[2];
const only = process.argv[3];
(async () => {
  const b = await chromium.launch();
  for (const s of (process.env.SCHEMES || "1,2,3").split(","))
    for (const st of ["login", "user", "pw", "error", "reg1", "reg2"])
      for (const [w, h] of [
        [1440, 900],
        [390, 844],
      ]) {
        const id = `${s}-${st}-${w}`;
        if (only && !id.startsWith(only)) continue;
        if (w === 390 && !["login", "pw", "reg2"].includes(st)) continue;
        const p = await b.newPage({ viewport: { width: w, height: h } });
        await p.route("**/api/v1/**", (r) =>
          r.fulfill({
            status: 401,
            contentType: "application/json",
            body: '{"error":{"code":"auth_required"}}',
          }),
        );
        await p.goto(
          `http://127.0.0.1:3100/auth-proposals?s=${s}&state=${st}&m=${w === 390 ? 1 : 0}`,
          { waitUntil: "networkidle", timeout: 120000 },
        );
        await p.addStyleTag({
          content:
            "nextjs-portal{display:none!important} *{transition:none!important;animation-play-state:paused!important}",
        });
        await p.mouse.move(w * 0.7, h * 0.45);
        await p.waitForTimeout(1200);
        await p.screenshot({
          path: `${OUT}/${s}/${st}-${w}.png`,
          fullPage: w === 390,
        });
        await p.close();
      }
  await b.close();
})();
