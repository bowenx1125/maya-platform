// Compares UI copy + a11y names of the current app (pw dumps) vs each mockup (audit/*.json).
// Data strings (non-ASCII mock content, dates, versions, email, user/assistant message text) are excluded and listed.
import fs from "fs";
const D = "/workspace/maya-chatform/pw/dumps/",
  A = "/workspace/maya-ui/proposals/chatform/audit/";
const isData = (s) =>
  /[^\x00-\x7F]/.test(s) ||
  /^\d+\/\d+\/\d{4}$/.test(s) ||
  /^V\d/.test(s) ||
  /@/.test(s) ||
  s === "Why?";
const keys = (d) => {
  const k = new Set();
  d.texts.forEach((t) => k.add("text:" + t));
  d.attrs.forEach((a) => {
    for (const f of ["aria", "title", "alt", "ph", "testid"])
      if (a[f]) k.add(f + ":" + a[f]);
  });
  return k;
};
let total = 0;
const rep = {};
for (const sc of ["A", "B", "C"])
  for (const st of ["list", "create", "empty", "newconv", "error", "errfold"])
    for (const w of [1440, 390]) {
      const cur = JSON.parse(
        fs.readFileSync(
          D + (st === "errfold" ? "error" : st) + "-" + w + ".json",
        ),
      );
      const MJ = JSON.parse(fs.readFileSync(A + `${sc}-${st}-${w}.json`));
      const mk = keys(MJ);
      (MJ.hiddenTexts || []).forEach((t) => mk.add("text:" + t)); // data-dependent copy present in markup (e.g. "No Teams yet." when Teams list is non-empty)
      let need = [...keys(cur)].filter((k) => !isData(k.replace(/^\w+:/, "")));
      if (st === "errfold")
        need = need.filter((k) => !/^text:Check status|^aria:Dismiss/.test(k)); // folded badge: actions reappear when the badge is opened; message stays in an sr-only role=status
      if (st === "create" && w === 1440)
        need = need.filter((k) => k !== "text:New"); // intentional: sidebar New removed; in create mode the page header shows Back/Done instead (scheme spec)
      const miss = need.filter(
        (k) =>
          !mk.has(k) &&
          !(
            k.startsWith("text:") &&
            [...mk].some((m) => m.endsWith(":" + k.slice(5)))
          ),
      );
      rep[`${sc}/${st}-${w}`] = miss;
      total += miss.length;
    }
console.log(JSON.stringify(rep, null, 0).replace(/\],/g, "],\n"));
console.log("TOTAL MISSING", total);
