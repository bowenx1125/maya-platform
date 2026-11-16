#!/usr/bin/env node
/**
 * Capture Batch 4 proposal stills + dance preview videos via Chrome.
 * Proposal-only tooling; not part of the product build.
 */
import { spawn, execFileSync } from "node:child_process";
import { createServer } from "node:http";
import {
  readFileSync,
  mkdirSync,
  existsSync,
  writeFileSync,
  unlinkSync,
} from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)));
const PORT = 8765;
const CHROME = process.env.CHROME || "google-chrome";
const DISPLAY = process.env.DISPLAY || ":1";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".js": "text/javascript",
};

function serve() {
  return new Promise((resolveServer) => {
    const server = createServer((req, res) => {
      const url = new URL(req.url || "/", `http://127.0.0.1:${PORT}`);
      let path = decodeURIComponent(url.pathname);
      if (path.endsWith("/")) path += "index.html";
      const file = resolve(ROOT, "." + path);
      if (!file.startsWith(ROOT) || !existsSync(file)) {
        res.writeHead(404);
        res.end("missing");
        return;
      }
      res.writeHead(200, {
        "content-type": MIME[extname(file)] || "application/octet-stream",
      });
      res.end(readFileSync(file));
    });
    server.listen(PORT, "127.0.0.1", () => resolveServer(server));
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function run(cmd, args, opts = {}) {
  return new Promise((resolvePromise) => {
    const child = spawn(cmd, args, {
      stdio: opts.stdio || "ignore",
      env: opts.env || process.env,
    });
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
    }, opts.timeoutMs || 20000);
    child.on("exit", () => {
      clearTimeout(timer);
      resolvePromise();
    });
  });
}

async function shot(url, out, { width = 1480, height = 1000 } = {}) {
  mkdirSync(dirname(out), { recursive: true });
  if (existsSync(out)) unlinkSync(out);
  await run(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-sandbox",
      "--hide-scrollbars",
      "--force-device-scale-factor=1",
      `--window-size=${width},${height}`,
      `--screenshot=${out}`,
      url,
    ],
    { timeoutMs: 18000 },
  );
  if (!existsSync(out)) throw new Error(`screenshot missing: ${out}`);
  console.log("shot", out, existsSync(out) ? `${readFileSync(out).length}b` : "MISSING");
}

async function recordDance(id, outMp4) {
  mkdirSync(dirname(outMp4), { recursive: true });
  const url = `http://127.0.0.1:${PORT}/436-mascot-dance/animations.html?shot=${id}`;
  const profile = `/tmp/maya-batch4-chrome-${id}-${Date.now()}`;
  mkdirSync(profile, { recursive: true });
  const chrome = spawn(
    CHROME,
    [
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--disable-infobars",
      "--no-default-browser-check",
      "--window-size=920,720",
      "--window-position=80,60",
      `--app=${url}`,
    ],
    { env: { ...process.env, DISPLAY }, stdio: "ignore" },
  );
  await sleep(2200);
  const raw = outMp4.replace(/\.mp4$/, ".raw.mp4");
  await run(
    "ffmpeg",
    [
      "-y",
      "-video_size",
      "880x640",
      "-framerate",
      "30",
      "-f",
      "x11grab",
      "-i",
      `${DISPLAY}+90,90`,
      "-t",
      "3.0",
      "-an",
      "-pix_fmt",
      "yuv420p",
      raw,
    ],
    { timeoutMs: 15000 },
  );
  const gif = outMp4.replace(/\.mp4$/, ".gif");
  await run(
    "ffmpeg",
    [
      "-y",
      "-i",
      raw,
      "-vf",
      "fps=16,scale=720:-2:flags=lanczos",
      "-loop",
      "0",
      gif,
    ],
    { timeoutMs: 20000 },
  );
  await run(
    "ffmpeg",
    [
      "-y",
      "-i",
      raw,
      "-c:v",
      "libx264",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      outMp4,
    ],
    { timeoutMs: 20000 },
  );
  chrome.kill("SIGKILL");
  console.log("video", outMp4, existsSync(gif) ? `+ ${gif}` : "");
}

const STILLS = [
  ["434-debate-tone/mockups.html?shot=current-1440", "434-debate-tone/assets/current-check-card-1440.png", 1480, 620],
  ["434-debate-tone/mockups.html?shot=a-1440", "434-debate-tone/assets/option-a-1440.png", 1480, 620],
  ["434-debate-tone/mockups.html?shot=a-390", "434-debate-tone/assets/option-a-390.png", 430, 560],
  ["434-debate-tone/mockups.html?shot=b-1440", "434-debate-tone/assets/option-b-1440.png", 1480, 620],
  ["434-debate-tone/mockups.html?shot=b-390", "434-debate-tone/assets/option-b-390.png", 430, 560],
  ["434-debate-tone/mockups.html?shot=c-1440", "434-debate-tone/assets/option-c-1440.png", 1480, 620],
  ["434-debate-tone/mockups.html?shot=c-390", "434-debate-tone/assets/option-c-390.png", 430, 560],
  ["437-student-sidebar/mockups.html?shot=current-1440", "437-student-sidebar/assets/current-1440.png", 1480, 960],
  ["437-student-sidebar/mockups.html?shot=current-390", "437-student-sidebar/assets/current-390.png", 430, 900],
  ["437-student-sidebar/mockups.html?shot=teacher-ref-1440", "437-student-sidebar/assets/teacher-ref-1440.png", 1480, 960],
  ["437-student-sidebar/mockups.html?shot=a-1440", "437-student-sidebar/assets/option-a-1440.png", 1480, 960],
  ["437-student-sidebar/mockups.html?shot=a-390", "437-student-sidebar/assets/option-a-390.png", 430, 900],
  ["437-student-sidebar/mockups.html?shot=b-1440", "437-student-sidebar/assets/option-b-1440.png", 1480, 960],
  ["437-student-sidebar/mockups.html?shot=b-390", "437-student-sidebar/assets/option-b-390.png", 430, 900],
  ["437-student-sidebar/mockups.html?shot=c-1440", "437-student-sidebar/assets/option-c-1440.png", 1480, 960],
  ["437-student-sidebar/mockups.html?shot=c-390", "437-student-sidebar/assets/option-c-390.png", 430, 900],
  ["436-mascot-dance/animations.html?shot=current", "436-mascot-dance/assets/current-idle.png", 900, 720],
  ["436-mascot-dance/animations.html?shot=a", "436-mascot-dance/assets/option-a-still.png", 900, 720],
  ["436-mascot-dance/animations.html?shot=b", "436-mascot-dance/assets/option-b-still.png", 900, 720],
  ["436-mascot-dance/animations.html?shot=c", "436-mascot-dance/assets/option-c-still.png", 900, 720],
];

for (const page of [
  "434-debate-tone/mockups.html",
  "437-student-sidebar/mockups.html",
  "436-mascot-dance/animations.html",
]) {
  const full = join(ROOT, page);
  let html = readFileSync(full, "utf8");
  if (!html.includes("BATCH4_SHOT_BOOT")) {
    html = html.replace(
      "</head>",
      `<script id="BATCH4_SHOT_BOOT">(()=>{const s=new URLSearchParams(location.search).get("shot");if(!s)return;document.documentElement.dataset.shot=s;const apply=()=>{document.body.dataset.shot=s;const sheet=document.querySelector(".sheet");if(sheet)sheet.style.display="none";for(const el of document.querySelectorAll(".shot")){el.style.display=el.getAttribute("data-id")===s?"block":"none";}};if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",apply);else apply();})();</script></head>`,
    );
    writeFileSync(full, html);
  }
}

const server = await serve();
try {
  for (const [path, out, w, h] of STILLS) {
    await shot(`http://127.0.0.1:${PORT}/${path}`, join(ROOT, out), {
      width: w,
      height: h,
    });
  }
  for (const id of ["a", "b", "c"]) {
    await recordDance(id, join(ROOT, `436-mascot-dance/assets/option-${id}.mp4`));
  }
  console.log("done");
} catch (err) {
  console.error(err);
  process.exitCode = 1;
} finally {
  server.close();
}
