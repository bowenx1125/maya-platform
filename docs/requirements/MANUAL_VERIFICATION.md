# Manual verification — the debate overhaul

Written for Bowen to check the four phases of `DEBATE_OVERHAUL_PLAN.md` by hand.
Ordered so each step leaves the system ready for the next one. Every item says
what you should see and what a failure looks like, so a "no" is unambiguous.

The automated gate (`pnpm check`) and CI both pass; this document is for the
things a test cannot judge — whether a screen reads well, and whether the
self-healing works when you are the one stuck.

---

## 0. Start the stack

```bash
cd ~/Desktop/Maya/maya-platform && docker compose up -d
```

Wait for `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/` to
return `200`.

**Then check the classroom address**, which is itself the Phase 3 fix:

```bash
python3 scripts/refresh_classroom_address.py
```

- **Pass:** it prints either `already http://<your LAN ip>:8080`, or an old →
  new line telling you to run `docker compose up -d`.
- **Fail:** it cannot find a LAN address, or it rewrites something other than
  that one line in `.env`.

Sign in at `http://localhost:8080` as **Maya**.

---

## 1. Phase 1 — what the screens say

A visual sweep. Nothing to click through; you are reading.

| Where          | Should be                                                                                               | Was                                                             |
| -------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| Sign-in page   | four buttons reading only `Bowen` `Jade` `Kaikai` `Maya`                                                | name + role                                                     |
| Top bar        | `Dashboard` `Debates`, no name and no `TEACHER VIEW` pill on the right                                  | both present                                                    |
| Dashboard      | the composition strip with no sentence under its heading                                                | had a lede                                                      |
| Any other page | **no** composition strip at all                                                                         | on every page                                                   |
| Agent card     | large name, description, then two pills: version and the group's name                                   | Active/Published badges + evidence-file count                   |
| Agent page     | the Agent's own description under its name; group card titled with the group's name, members listed A→Z | a note about hidden fields; a generic "Producing group" heading |
| Anywhere       | no small grey sentence under a section heading                                                          | many                                                            |

**One thing to look at closely:** the version pill is **green** when the
published release is the newest work, **amber** when a student has a newer
draft that is not published. Both Agents should be green now. That colour is
derived from the Agent's own draft/published pointers, not a status word — so
if you publish a new version from a student account and come back, it should
go amber then green again without anyone touching code.

---

## 2. Phase 2 — the three bugs

> **Do §4.1 first.** Bowen's own pass found something this section assumed
> worked: a debate could run to completion and display none of its speeches.
> Pre-warm generated each turn before the lesson reached it, and a turn that
> was already prepared never announced itself, so playback never started and
> nothing was published. It is fixed — but check that the speeches appear
> before checking anything downstream of them.

### 2.1 Interaction entry survives a finished lesson

Open `Debates` → a debate marked **Finished** that ran to completion → its
control page.

- **Pass:** an `Interaction` button sits with Start / Next / Back under the 3D
  face.
- **Fail:** no such button on a debate whose every turn is public.

The old bug: starting _another_ debate took this button away, because the gate
read a playback status that a later action changes. Test it: start any other
debate, come back here, the button must still be there.

### 2.2 A real report actually generates

From that debate → `Interaction` → **Regenerate**.

- **Pass:** within about a minute the report reads **Ready** with a revision
  number, and the English Markdown appears below it.
- **Fail:** it sits on `Generating` forever, or goes to `Failed`.

If it fails, the reason is now recorded — tell me the `safe_error_code` on the
revision rather than just "the report failed".

### 2.3 Vote totals name the Agents

Same page, the vote block.

- **Pass:** `A · Laozi`, `B · Plato` — names.
- **Fail:** raw UUIDs.

---

## 3. Phase 3 — get yourself unstuck without a terminal

This is the phase worth your time, because it is the one whose value only
shows when something has gone wrong. **Break it on purpose.**

### 3.1 A lesson left running blocks the course

1. Start a debate and leave it running. Do not finish it.
2. Go to `Debates` and create a second one, open it, press **Start**.

- **Pass:** it refuses, names **the debate that is holding the slot by its
  topic**, and shows a **Release** button right there under the error. Press it
  twice (it arms, then acts). Start now works.
- **Fail:** the error says something else is running without saying what, or
  the only way out is the terminal.

Also check the list itself: the running debate should carry its own `Release`
button beside it.

> The audit trail matters here. Every release records **your teacher account**,
> not an anonymous operator. That was the condition for moving this out of a
> CLI, so it is worth one check:
> `docker exec maya-platform-backend-1 python -c "import sqlite3;c=sqlite3.connect('/app/data/maya.sqlite3');print(c.execute(\"SELECT event_type,actor_kind,actor_id FROM audit_logs ORDER BY rowid DESC LIMIT 1\").fetchone())"`
> — `actor_id` must not be `None`.

### 3.2 A dead turn offers a real button

If a turn ever fails during a lesson, the failure card should carry
**Regenerate**, and pressing it should retry that turn.

- **Fail:** the card says "you can retry this turn" and offers nothing to press.

This one is hard to force on purpose. If you never see it, say so — I would
rather know it went unverified than assume it works.

### 3.3 A dropped connection offers the action that fixes it

Stop the backend mid-lesson (`docker compose stop backend`), watch the stage,
then start it again.

- **Pass:** the overlay names the cause and offers **Reconnect**. For an
  expired session it offers **Sign in**; for a superseded controller or an
  address mismatch, **Reload**.
- **Fail:** an accurate diagnosis with no button.

---

## 4. Phase 4 — the new behaviour

### 4.1 A draft warms itself, one at a time

1. Create a debate. You land back on the list.
2. Watch its badge.

- **Pass:** it reads **Thinking 25% → 50% → …**, then **Ready** at 100%, and
  **pressing Start makes the first speech appear on screen**. Open
  it before it reaches 100% and press Start — the cached turns play at once and
  only the uncached ones make you wait.
- **Fail:** it sits on `Draft` and nothing generates until you press Start.

**Then the scheduler rule.** Create a second draft while the first is warming:

- **Pass:** the first stops where it is (keeping what it cached) and the second
  starts warming. Only one warms at a time.
- **Fail:** both climb at once, or the first loses its cached turns.

**End works the first time.** Press `End` during a running lesson.

- **Pass:** it finishes. No "The classroom state changed. Refresh and try
  again." That message meant the page held a version one event behind the
  server; End now re-reads and retries once by itself.
- **Fail:** you are asked to refresh and press it again.

**And the difference between yielding and ending:** press `End` on a draft.

- **Pass:** it never warms again.
- **Fail:** it resumes warming later.

### 4.2 A debate held in Chinese

Switch the language control to **中文**, then create and Start a debate.

- **Pass:** the speeches are in Chinese. The evidence panel, the report and the
  scores all work the same.
- **Fail:** English speeches, or a turn that fails with
  `turn_generation_failed`.

**Expect this to fail more often than English does.** The structural rules — a
claim must be an exact substring of its own speech — were tuned against English
output. That is prompt quality, not the language lock; the lock itself is
verified (an English speech in a Chinese debate is rejected).

Switching the language control _after_ Start must change only the interface,
never the debate. Check that: start in Chinese, switch to English, the
speeches stay Chinese.

### 4.3 The interaction page ends at the report

Open any finished debate's `Interaction`.

- **Pass, in this order:** votes (a pie) + barrages → **Agent scores** (bars) →
  **Report** → nothing below it. No "M13 · ANONYMOUS AUDIENCE", no
  "MAYA · CIVILIZATION MUTUAL LEARNING", no test-translation panel, no
  duplicated vote/barrage/history blocks at the bottom.
- **Fail:** any of those still present.

The scores: direct evidence +5, indirect +2, no evidence 0, summed per Agent
over its public turns. Cross-check one Agent by opening `Check RAG` on its
turns and counting — the panel and the chart read the same function, so they
must agree.

### 4.4 Audio is released, text is not

Finish a debate that ran every turn.

- **Pass:** its audio files are gone, the page says the audio is no longer
  retained, and every speech, evidence chain and the interaction page are still
  there.
- **Fail:** the text is affected, or a **partially** finished debate loses its
  audio — only complete runs are released.

---

## 5. The overfitting check

The failure this guards against is real: five sites once hard-coded
`participants * 2`, so a 3-agent 4-round debate looked incomplete to all of
them. **Do not only run 2 × 2.**

Create and start one debate of each shape you care about — at minimum
**2 agents × 2 rounds**, **3 × 4**, and **5 × 5** — and for each check:

- the setup page's turn count matches agents × rounds
- the pre-warm percentage reaches 100%, not some other ceiling
- every turn generates
- after Finish, the `Interaction` button appears

I ran all sixteen shapes for the planned turn count and the pre-warm
denominator. What I did **not** run to completion sixteen times is the full
lesson with real provider calls — that is hours of generation. If you have one
shape you care about most for the demo, run that one end to end.

---

## 6. What I could not verify for you

Stated plainly so you know where the thin ice is.

1. **Pre-warm has no automated regression.** It is disabled under the test
   client on purpose: it writes between the test's own statements and no
   assertion can survive that race. The scheduler's rules are unit-tested, but
   _pre-warm interacting with real playback_ is covered only by my manual runs
   and yours. If anyone changes how turns are claimed, this is the first thing
   to re-check by hand.

2. **Historical per-turn audio replay** returns 403 by design. Replay works for
   the current turn only. Making history replayable needs a server-side review
   I did not do.

3. **The changed-LAN-address recovery is one command, not zero.** I tried to
   make the origin check accept any private address and reverted it: a test
   pins that other private addresses are rejected, and the WebSocket guard says
   why a Host-derived allow-list must never exist. That control is doing its
   job, so the chore stays.

4. **Chinese prompt quality**, as in 4.2.

---

## If something fails

Tell me which numbered step, and paste what you saw. For a backend failure the
useful line is now the `safe_error_code`:

```bash
docker logs maya-platform-backend-1 --tail 60 | grep -iE "failed|rejected|rule="
```
