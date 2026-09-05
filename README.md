# Maya Teaching Platform

Maya is a classroom tool for teaching how a point of view gets built and
defended.

Students write an **Agent** — a character with a stated persona and a set of
Markdown files it is allowed to draw on. When the group is happy with it they
**publish** it, which freezes both the persona and the files so nobody can
quietly change them later.

The teacher then picks two to five published Agents and runs a **debate**. The
Agents take turns; each speech is generated from that Agent's own persona and
its own frozen evidence, and every claim in it can be traced back to the file it
came from. While the debate runs the class can vote and send messages
anonymously from their phones. At the end Maya writes a report about what the
debate covered.

Everything runs on one machine. Nothing is uploaded anywhere unless you
deliberately turn on a real AI provider, and the platform ships fully working
without one.

---

## Before you start

You need three things installed:

- **Docker Desktop** — runs the whole platform. <https://docker.com>
- **Node.js 24** and **pnpm** — build the web interface.
- **Git** — to download the code.

That is all. You do **not** need Python, an AI provider account, or an API key
to run a class.

---

## Download and start it, the first time

```sh
git clone https://github.com/bowenx1125/maya-platform.git
cd maya-platform
pnpm install --frozen-lockfile
pnpm bootstrap:local
docker compose up -d --build
```

`pnpm bootstrap:local` asks you once for a password that everyone in the demo
will share, and writes it to a private file that is never committed. It refuses
to overwrite an existing one, so you only ever run it once.

The last command takes a few minutes the first time. When it finishes:

```sh
docker compose ps
```

Wait until `backend` and `frontend` both say **healthy**, then open
**<http://localhost:8080>**.

Sign in as **Maya** (the teacher). The platform starts with a course already
set up: one teacher, three students (Bowen, Kaikai, Jade), and three published
Agents — Socrates, Plato and Laozi — so you can run a debate immediately
without building anything first.

---

## Starting it again later

```sh
cd maya-platform
docker compose up -d
```

Open <http://localhost:8080> once `docker compose ps` says healthy.

If you have pulled new code, add `--build`:

```sh
git pull && docker compose up -d --build
```

**If the classroom link stops working after you change networks**, your
machine's address changed. One command fixes it:

```sh
python3 scripts/refresh_classroom_address.py
docker compose up -d
```

(`up -d`, not `start` — `start` reuses the old settings.)

---

## Using it

### Run a debate

1. **Debates → New debate.** Type a question, click two to five Agents in the
   order you want them to speak, and choose how many rounds (2–5).
2. **Create.** You land back on the list, and the debate starts preparing
   itself — the badge counts up, `Thinking 25% → 50% → …`, then `Ready`.
   You can open it and start before it reaches 100%; the prepared turns play
   immediately and only the unprepared ones make you wait.
3. **Open it and press Start.** The first Agent speaks. Press **Next** for each
   following turn — the room moves when you decide it moves, not on a timer.
4. Under each speech, **Check RAG** opens the evidence: which claim came from
   which file, and whether that claim had direct evidence (+5), indirect (+2),
   or none (+0).
5. **End** finishes the debate.

Only one debate can run at a time per course. If you left an old one running,
the platform tells you which one and gives you a **Release** button right
there — you never need a terminal to get unstuck.

### Let the class join in

From a finished debate, open **Interaction**. Students scan the QR code on
their phones to vote and send messages. Their votes are anonymous.

When you close the interaction, Maya writes the report. The same page shows,
top to bottom: the vote, the messages, each Agent's evidence score, and the
report.

### English or Chinese

The **中文 / English** switch in the top bar changes the interface at any time.

It also decides what language the **debate** is generated in — but only at the
moment you press Start. After that the debate stays in the language it began
in, because every turn is written from the turns before it and pre-prepared
ahead of you. Switching afterwards changes the interface only.

---

## Turning on a real AI provider

**You do not need this.** Maya ships with every AI piece simulated, and a whole
class runs that way. Turn a real provider on only if you specifically want real
generated text.

Six switches decide what is real; all of them start as `mock`. Three can use
DashScope: `LLM_PROVIDER` (the debate), `MAYA_REPORT_PROVIDER` (the report) and
`EMBEDDING_PROVIDER` (evidence search). Voice and text-to-speech stay simulated.

**See what is real right now:**

```sh
curl -s http://localhost:8080/api/v1/demo/composition | python3 -m json.tool
```

The teacher home shows the same thing, so a class is never misled about which
pieces are real.

**Step 1 — install the reviewed provider policy (once per machine).** An API
key on its own is not enough: without this, every turn stops with
`provider_preflight_blocked`. This reads each supplier's published document,
records its hash and when you read it, and stores the result outside `data/` so
resetting the runtime does not destroy it.

```sh
docker compose stop backend
uv run --directory backend python ../scripts/import_provider_review.py --accept-account-settings
docker compose up -d
```

Stop the backend first — it holds the database lock.

**Step 2 — turn the switches on:**

```sh
sed -i '' 's/^LLM_PROVIDER=.*/LLM_PROVIDER=dashscope/; s/^MAYA_REPORT_PROVIDER=.*/MAYA_REPORT_PROVIDER=dashscope/; s/^EMBEDDING_PROVIDER=.*/EMBEDDING_PROVIDER=dashscope/' .env && docker compose up -d
```

On Linux, `sed -i` without the `''`.

**Going back to simulated:** the same command with `mock` instead of
`dashscope`. Your imported policy stays, so turning it on again later needs
only step 2.

Optional: `DEMO_AUTO_CONFIRM_PROVIDER=true` in `.env` confirms the per-turn
disclosure for you so a lesson is not interrupted. Every automatic confirmation
is still logged, and removing the line restores confirming by hand.

[docs/REAL_PROVIDER_SETUP.md](docs/REAL_PROVIDER_SETUP.md) has the full detail.

---

## Stopping, resetting, and looking at logs

```sh
docker compose stop                    # stop, keeping everything
docker compose logs -f --tail=100      # watch what the platform is doing
```

To throw away all debates, reports and recordings and start from a clean seed:

```sh
docker compose down && rm -rf data && docker compose up -d --build
```

That deletes the runtime database. It does **not** delete your `.env` or your
imported provider policy.

Avoid `docker compose down -v` — it removes Docker volumes, and ordinary runtime
data lives under `data/`.

---

## For developers

Run every check the way CI does:

```sh
pnpm check
```

Backend tests must run from `backend/` — running them from the repository root
loads the real `.env` and fails origin-sensitive tests for reasons unrelated to
your change.

- [AGENTS.md](AGENTS.md) — the working agreement for changing this repository,
  including the four-step procedure for changing the frozen API contract.
- [docs/PROJECT.md](docs/PROJECT.md) — what the product is and where it stands.
- [docs/requirements/MANUAL_VERIFICATION.md](docs/requirements/MANUAL_VERIFICATION.md)
  — how to check the classroom flow by hand.

**What runs:**

| Service    | Role                                                           |
| ---------- | -------------------------------------------------------------- |
| `gateway`  | Caddy, one origin on port `8080`, routing `/api/*` and `/ws/*` |
| `frontend` | Next.js — student, teacher and classroom screens               |
| `backend`  | FastAPI on Python 3.12 with SQLite and FFmpeg                  |

The browser only ever calls Maya's own `/api/v1` routes on the same origin.
Supplier names, model ids, API keys and file paths stay on the server; the
teacher-only provider disclosure is the single exception, and it shows only the
reviewed supplier name, region, purpose, outbound field classes and policy
hashes.

**Private files.** Git holds source and non-secret fixtures only. The ignored
`.env` and `backend/config/demo-accounts/accounts.private.md` are the only
private runtime materials, and `data/` is disposable.

**Frozen frontend toolchain.** TypeScript `5.9.3`, ESLint `9.39.1`, Next.js
`16.3.3`, React `19.2.8`, Vitest `4.1.11`, Vite `8.2.2`, jsdom `29.0.1`.
ESLint 9 is a deliberate override: ESLint 10 crashes inside the Next.js 16.3.3
parser before it lints anything. TypeScript 5.9.3 is required by
openapi-typescript 7.13.0, and jsdom 29.0.1 matches the frozen Node 24.14
runtime.
